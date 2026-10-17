from __future__ import annotations

import json
from pathlib import Path

from coderca.application import DiagnosisApplicationService
from coderca.benchmark import load_task_1_manifest, materialize_task_1
from coderca.context_builder import DiagnosisTaskContext
from coderca.contracts import TaskManifest
from coderca.model_provider import FakeModelProvider
from coderca.run_store import RunStore
from coderca.tool_runtime import ToolRuntime


def proposal_payload(symbol: str = "package.module.select_value") -> dict[str, object]:
    return {
        "root_symbol": symbol,
        "location_description": None,
        "mechanism": "A truthiness fallback discards explicit zero.",
        "falsification_criterion": "The code distinguishes zero from missing.",
    }


def resolved_task(valid_manifest_data: dict[str, object]) -> DiagnosisTaskContext:
    return DiagnosisTaskContext(
        manifest=TaskManifest.model_validate(valid_manifest_data),
        ci_failure_excerpt="pytest failed: expected 1, got 2",
        ci_failure_artifact=str(valid_manifest_data["ci_log"]),
    )


def test_start_diagnosis_forms_only_h1_and_persists_observable_artifacts(
    tmp_path: Path, valid_manifest_data: dict[str, object]
) -> None:
    provider = FakeModelProvider(
        {"form_hypothesis": {"hypothesis": proposal_payload()}}
    )
    service = DiagnosisApplicationService(
        provider=provider, run_store=RunStore(tmp_path / "runs")
    )

    result = service.start_diagnosis(resolved_task(valid_manifest_data))

    assert result.stage == "diagnosing"
    assert result.status == "in_progress"
    assert result.stop_reason is None
    assert [item.hypothesis_id for item in result.hypothesis_history] == ["H1"]
    assert result.hypothesis_history[0].root_symbol == "package.module.select_value"
    assert provider.structured_calls == ["form_hypothesis"]

    events = [json.loads(line) for line in result.events_path.read_text().splitlines()]
    assert [event["stage"] for event in events] == [
        "preparing",
        "forming_hypothesis",
        "diagnosing",
    ]
    assert events[-1]["event_type"] == "hypothesis_formed"
    assert events[-1]["hypothesis_history"][0]["hypothesis_id"] == "H1"
    response_path = result.run_directory / events[-1]["model_response_artifact"]
    assert json.loads(response_path.read_text()) == {"hypothesis": proposal_payload()}
    assert "form-hypothesis-attempt-1.json" in str(response_path)

    report = json.loads(result.report_path.read_text())
    assert report["stage"] == "diagnosing"
    assert report["hypothesis_history"][0]["hypothesis_id"] == "H1"


def test_formation_context_is_reconstructed_from_resolved_task_not_raw_history(
    tmp_path: Path, valid_manifest_data: dict[str, object]
) -> None:
    provider = FakeModelProvider()
    task = DiagnosisTaskContext(
        manifest=TaskManifest.model_validate(valid_manifest_data),
        ci_failure_excerpt="failure-line\n" * 1_000,
        ci_failure_artifact="ci/failure.log",
    )

    DiagnosisApplicationService(
        provider=provider, run_store=RunStore(tmp_path / "runs")
    ).start_diagnosis(task)

    context = json.loads(provider.structured_requests[0]["user_prompt"])
    assert context["decision_type"] == "form_hypothesis"
    assert context["diagnosis_state"] == {
        "active_hypothesis_id": None,
        "hypothesis_history": [],
        "remaining_hypothesis_budget": 3,
        "remaining_tool_budget": valid_manifest_data["tool_call_limit"],
        "stage": "forming_hypothesis",
    }
    failure = context["task_context"]["ci_failure"]
    assert len(failure["excerpt"]) == 2_000
    assert failure["artifact_ref"] == "ci/failure.log"
    assert "conversation_history" not in context
    assert "model_responses" not in context


def test_first_invalid_formation_gets_one_fresh_schema_correction(
    tmp_path: Path, valid_manifest_data: dict[str, object]
) -> None:
    invalid_response: dict[str, object] = {"hypothesis": {}}
    valid_response = {"hypothesis": proposal_payload()}
    provider = FakeModelProvider(
        structured_response_sequences={
            "form_hypothesis": [invalid_response, valid_response]
        }
    )

    result = DiagnosisApplicationService(
        provider=provider, run_store=RunStore(tmp_path / "runs")
    ).start_diagnosis(resolved_task(valid_manifest_data))

    assert result.status == "in_progress"
    assert provider.structured_calls == ["form_hypothesis", "form_hypothesis"]
    first_context = json.loads(provider.structured_requests[0]["user_prompt"])
    second_context = json.loads(provider.structured_requests[1]["user_prompt"])
    assert "schema_correction" not in first_context
    assert second_context["schema_correction"]["attempt"] == 2
    assert second_context["schema_correction"]["failure_category"] == (
        "schema_mismatch"
    )
    assert json.dumps(invalid_response) not in json.dumps(second_context)

    events = [json.loads(line) for line in result.events_path.read_text().splitlines()]
    assert [event["event_type"] for event in events] == [
        "run_started",
        "stage_changed",
        "schema_correction_requested",
        "hypothesis_formed",
    ]


def test_h1_free_text_evidence_basis_triggers_bounded_schema_correction(
    tmp_path: Path, valid_manifest_data: dict[str, object]
) -> None:
    invalid_h1 = {
        "hypothesis": {
            **proposal_payload(),
            "evidence_basis": ["The writable path probably contains the defect."],
        }
    }
    provider = FakeModelProvider(
        structured_response_sequences={
            "form_hypothesis": [invalid_h1, {"hypothesis": proposal_payload()}]
        }
    )

    result = DiagnosisApplicationService(
        provider=provider, run_store=RunStore(tmp_path / "runs")
    ).start_diagnosis(resolved_task(valid_manifest_data))

    assert result.status == "in_progress"
    assert result.hypothesis_history[0].evidence_basis == ()
    events = [json.loads(line) for line in result.events_path.read_text().splitlines()]
    assert events[2]["event_type"] == "schema_correction_requested"
    assert events[2]["validation_errors"] == [
        {"loc": ["hypothesis", "evidence_basis"], "type": "extra_forbidden"}
    ]


def test_second_invalid_formation_finalizes_as_schema_failure(
    tmp_path: Path, valid_manifest_data: dict[str, object]
) -> None:
    invalid: dict[str, object] = {"hypothesis": {}}
    provider = FakeModelProvider(
        structured_response_sequences={"form_hypothesis": [invalid, invalid]}
    )

    result = DiagnosisApplicationService(
        provider=provider, run_store=RunStore(tmp_path / "runs")
    ).start_diagnosis(resolved_task(valid_manifest_data))

    assert result.stage == "finalizing"
    assert result.status == "failed"
    assert result.stop_reason == "schema_failure"
    assert result.hypothesis_history == ()
    events = [json.loads(line) for line in result.events_path.read_text().splitlines()]
    assert events[-1]["event_type"] == "run_failed"
    assert events[-1]["failure_category"] == "schema_failure"
    assert events[-1]["validation_errors"]


def test_two_diagnosis_runs_use_distinct_directories(
    tmp_path: Path, valid_manifest_data: dict[str, object]
) -> None:
    service = DiagnosisApplicationService(
        provider=FakeModelProvider(), run_store=RunStore(tmp_path / "runs")
    )
    task = resolved_task(valid_manifest_data)

    first = service.start_diagnosis(task)
    second = service.start_diagnosis(task)

    assert first.run_id != second.run_id
    assert first.run_directory != second.run_directory


def test_task_1_read_only_loop_reports_supported_root_cause_from_real_diff(
    tmp_path: Path,
) -> None:
    manifest = load_task_1_manifest()
    workspace = materialize_task_1(tmp_path / "workspace")
    task = DiagnosisTaskContext(
        manifest=manifest,
        ci_failure_excerpt="AssertionError: True is not false",
        ci_failure_artifact=manifest.ci_log,
    )
    provider = FakeModelProvider(
        {
            "form_hypothesis": {
                "hypothesis": {
                    "root_symbol": "AbstractBaseFlag.is_active_for_user",
                    "location_description": None,
                    "mechanism": "A truthiness guard ignores explicit False.",
                    "falsification_criterion": (
                        "The diff preserves an explicit None check."
                    ),
                }
            },
            "select_experiment": {
                "hypothesis_id": "H1",
                "purpose": "Inspect the only source change for the faulty commit.",
                "expected_observation": (
                    "The None check changed to a truthiness check."
                ),
                "falsification_relevance": ("A preserved None check would falsify H1."),
                "tool_name": "inspect_diff",
                "arguments": {"path": "waffle/models.py"},
            },
            "update_evidence": {
                "hypothesis_id": "H1",
                "observation_ref": "O1",
                "direction": "supporting",
                "explanation": (
                    "The diff replaces the explicit None check with truthiness."
                ),
            },
            "assess_hypothesis": {
                "outcome": "sufficiently_supported",
                "evidence_refs": ["E1"],
                "rationale": "The observed change directly implements the mechanism.",
            },
        }
    )
    service = DiagnosisApplicationService(
        provider=provider,
        run_store=RunStore(tmp_path / "runs"),
        tool_runtime=ToolRuntime(workspace, manifest),
    )

    result = service.start_diagnosis(task)

    assert result.stage == "finalizing"
    assert result.status == "completed"
    assert result.stop_reason == "read_only_diagnosis_complete"
    assert result.hypothesis_history[-1].root_symbol == (
        "AbstractBaseFlag.is_active_for_user"
    )
    assert result.hypothesis_history[-1].status == "supported"
    assert [item.evidence_id for item in result.evidence] == ["E1"]
    assert provider.structured_calls == [
        "form_hypothesis",
        "select_experiment",
        "update_evidence",
        "assess_hypothesis",
    ]
    report = json.loads(result.report_path.read_text())
    assert report["final_hypothesis"]["root_symbol"] == (
        "AbstractBaseFlag.is_active_for_user"
    )
    assert report["evidence"][0]["observation_ref"] == "O1"
    assert report["observations"][0]["tool_result_ref"] == "T1"
    artifact = result.run_directory / report["observations"][0]["artifact_ref"]
    assert "if self.everyone is not None" in artifact.read_text()


def test_rejected_h1_reformulates_h2_from_registered_evidence(
    tmp_path: Path,
) -> None:
    manifest = load_task_1_manifest()
    workspace = materialize_task_1(tmp_path / "workspace")
    task = DiagnosisTaskContext(
        manifest=manifest,
        ci_failure_excerpt="AssertionError: True is not false",
        ci_failure_artifact=manifest.ci_log,
    )
    provider = FakeModelProvider(
        structured_responses={
            "form_hypothesis": {
                "hypothesis": {
                    "root_symbol": "AbstractBaseFlag.get_flush_keys",
                    "location_description": None,
                    "mechanism": "The cache invalidation key changed.",
                    "falsification_criterion": (
                        "The Faulty Commit does not modify cache invalidation."
                    ),
                }
            },
            "reformulate_hypothesis": {
                "hypothesis": {
                    "root_symbol": "AbstractBaseFlag.is_active_for_user",
                    "location_description": None,
                    "mechanism": "A truthiness guard ignores explicit False.",
                    "falsification_criterion": (
                        "The implementation still uses an explicit None check."
                    ),
                },
                "evidence_refs": ["E1"],
            },
        },
        structured_response_sequences={
            "select_experiment": [
                {
                    "hypothesis_id": "H1",
                    "purpose": "Inspect whether the commit modifies cache keys.",
                    "expected_observation": "No cache key change is present.",
                    "falsification_relevance": "No such change falsifies H1.",
                    "tool_name": "inspect_diff",
                    "arguments": {"path": "waffle/models.py"},
                },
                {
                    "hypothesis_id": "H2",
                    "purpose": "Read the changed flag evaluation branch.",
                    "expected_observation": "The branch uses truthiness for everyone.",
                    "falsification_relevance": "An explicit None check falsifies H2.",
                    "tool_name": "read_code",
                    "arguments": {
                        "path": "waffle/models.py",
                        "start_line": 228,
                        "end_line": 238,
                    },
                },
            ],
            "update_evidence": [
                {
                    "hypothesis_id": "H1",
                    "observation_ref": "O1",
                    "direction": "contradicting",
                    "explanation": "The diff changes a boolean guard, not cache keys.",
                },
                {
                    "hypothesis_id": "H2",
                    "observation_ref": "O2",
                    "direction": "supporting",
                    "explanation": "The read code contains the truthiness guard.",
                },
            ],
            "assess_hypothesis": [
                {
                    "outcome": "falsified",
                    "evidence_refs": ["E1"],
                    "rationale": "E1 directly contradicts the cache mechanism.",
                },
                {
                    "outcome": "sufficiently_supported",
                    "evidence_refs": ["E2"],
                    "rationale": "E2 directly shows the faulty condition.",
                },
            ],
        },
    )

    result = DiagnosisApplicationService(
        provider=provider,
        run_store=RunStore(tmp_path / "runs"),
        tool_runtime=ToolRuntime(workspace, manifest),
    ).start_diagnosis(task)

    assert result.status == "completed"
    assert [item.status for item in result.hypothesis_history] == [
        "rejected",
        "supported",
    ]
    assert result.hypothesis_history[1].evidence_basis == ("E1",)
    assert [item.evidence_id for item in result.evidence] == ["E1", "E2"]
    reformulation_request = next(
        request
        for request in provider.structured_requests
        if request["schema_name"] == "reformulate_hypothesis"
    )
    context = json.loads(reformulation_request["user_prompt"])
    assert context["diagnosis_state"]["hypothesis_history"][0]["status"] == ("rejected")
    assert context["reformulation_knowledge"]["evidence"][0]["evidence_id"] == ("E1")
    assert (
        context["reformulation_knowledge"]["observations"][0]["observation_id"] == "O1"
    )
    assert "if self.everyone" not in reformulation_request["user_prompt"]


def test_loop_decision_allows_one_schema_correction_without_raw_history(
    tmp_path: Path,
) -> None:
    manifest = load_task_1_manifest()
    workspace = materialize_task_1(tmp_path / "workspace")
    task = DiagnosisTaskContext(
        manifest=manifest,
        ci_failure_excerpt="AssertionError: True is not false",
        ci_failure_artifact=manifest.ci_log,
    )
    provider = FakeModelProvider(
        structured_responses={
            "form_hypothesis": {
                "hypothesis": {
                    "root_symbol": "AbstractBaseFlag.is_active_for_user",
                    "location_description": None,
                    "mechanism": "A truthiness guard ignores explicit False.",
                    "falsification_criterion": "The code uses an explicit None check.",
                }
            },
            "select_experiment": {
                "hypothesis_id": "H1",
                "purpose": "Inspect the Faulty Commit diff.",
                "expected_observation": "The condition changed.",
                "falsification_relevance": "No condition change falsifies H1.",
                "tool_name": "inspect_diff",
                "arguments": {"path": "waffle/models.py"},
            },
            "assess_hypothesis": {
                "outcome": "sufficiently_supported",
                "evidence_refs": ["E1"],
                "rationale": "E1 directly supports the mechanism.",
            },
        },
        structured_response_sequences={
            "update_evidence": [
                {"hypothesis_id": "H1"},
                {
                    "hypothesis_id": "H1",
                    "observation_ref": "O1",
                    "direction": "supporting",
                    "explanation": "The diff contains the predicted condition change.",
                },
            ]
        },
    )

    result = DiagnosisApplicationService(
        provider=provider,
        run_store=RunStore(tmp_path / "runs"),
        tool_runtime=ToolRuntime(workspace, manifest),
    ).start_diagnosis(task)

    assert result.status == "completed"
    update_requests = [
        request
        for request in provider.structured_requests
        if request["schema_name"] == "update_evidence"
    ]
    assert len(update_requests) == 2
    corrected_context = json.loads(update_requests[1]["user_prompt"])
    assert corrected_context["schema_correction"]["attempt"] == 2
    assert "raw_response" not in corrected_context
    events = [json.loads(line) for line in result.events_path.read_text().splitlines()]
    assert any(event["event_type"] == "schema_correction_requested" for event in events)


def test_second_invalid_loop_decision_finalizes_with_preserved_history(
    tmp_path: Path,
) -> None:
    manifest = load_task_1_manifest()
    workspace = materialize_task_1(tmp_path / "workspace")
    task = DiagnosisTaskContext(
        manifest=manifest,
        ci_failure_excerpt="AssertionError: True is not false",
        ci_failure_artifact=manifest.ci_log,
    )
    provider = FakeModelProvider(
        structured_responses={
            "form_hypothesis": {"hypothesis": proposal_payload()},
            "select_experiment": {
                "hypothesis_id": "H1",
                "purpose": "Inspect the diff.",
                "expected_observation": "A discriminating source change.",
                "falsification_relevance": "No relevant change falsifies H1.",
                "tool_name": "inspect_diff",
                "arguments": {"path": "waffle/models.py"},
            },
        },
        structured_response_sequences={
            "update_evidence": [{"bad": True}, {"bad": True}]
        },
    )

    result = DiagnosisApplicationService(
        provider=provider,
        run_store=RunStore(tmp_path / "runs"),
        tool_runtime=ToolRuntime(workspace, manifest),
    ).start_diagnosis(task)

    assert result.status == "failed"
    assert result.stop_reason == "schema_failure"
    assert [item.hypothesis_id for item in result.hypothesis_history] == ["H1"]
    report = json.loads(result.report_path.read_text())
    assert report["hypothesis_history"][0]["hypothesis_id"] == "H1"
    assert report["observations"][0]["tool_result_ref"] == "T1"


def test_h3_inconclusive_stops_without_forming_h4(
    tmp_path: Path, valid_manifest_data: dict[str, object]
) -> None:
    workspace = tmp_path / "workspace"
    source = workspace / "src" / "module.py"
    source.parent.mkdir(parents=True)
    source.write_text("value = 1\n")
    manifest = TaskManifest.model_validate(valid_manifest_data)
    provider = FakeModelProvider(
        structured_responses={
            "form_hypothesis": {"hypothesis": proposal_payload("module.h1")}
        },
        structured_response_sequences={
            "select_experiment": [
                {
                    "hypothesis_id": f"H{index}",
                    "purpose": f"Inspect code for H{index}.",
                    "expected_observation": "A discriminating implementation fact.",
                    "falsification_relevance": "The opposite fact falsifies it.",
                    "tool_name": "read_code",
                    "arguments": {
                        "path": "src/module.py",
                        "start_line": 1,
                        "end_line": 1,
                    },
                }
                for index in range(1, 4)
            ],
            "update_evidence": [
                {
                    "hypothesis_id": f"H{index}",
                    "observation_ref": f"O{index}",
                    "direction": "inconclusive",
                    "explanation": "The Observation does not discriminate this H.",
                }
                for index in range(1, 4)
            ],
            "assess_hypothesis": [
                {
                    "outcome": "inconclusive",
                    "evidence_refs": [f"E{index}"],
                    "rationale": "No more useful Experiment is available for this H.",
                }
                for index in range(1, 4)
            ],
            "reformulate_hypothesis": [
                {
                    "hypothesis": {
                        **proposal_payload(f"module.h{index}"),
                        "mechanism": f"Materially different mechanism {index}.",
                    },
                    "evidence_refs": [f"E{index - 1}"],
                }
                for index in range(2, 4)
            ],
        },
    )

    result = DiagnosisApplicationService(
        provider=provider,
        run_store=RunStore(tmp_path / "runs"),
        tool_runtime=ToolRuntime(workspace, manifest, enforce_faulty_commit=False),
    ).start_diagnosis(resolved_task(valid_manifest_data))

    assert result.status == "completed"
    assert result.stop_reason == "hypothesis_budget_exhausted"
    assert [item.hypothesis_id for item in result.hypothesis_history] == [
        "H1",
        "H2",
        "H3",
    ]
    assert all(item.status == "inconclusive" for item in result.hypothesis_history)
    assert provider.structured_calls.count("reformulate_hypothesis") == 2


def test_eight_tool_calls_stop_before_a_ninth_execution(
    tmp_path: Path, valid_manifest_data: dict[str, object]
) -> None:
    workspace = tmp_path / "workspace"
    source = workspace / "src" / "module.py"
    source.parent.mkdir(parents=True)
    source.write_text("value = 1\n")
    manifest = TaskManifest.model_validate(valid_manifest_data)
    select = {
        "hypothesis_id": "H1",
        "purpose": "Inspect another bounded code fact.",
        "expected_observation": "A fact that discriminates H1.",
        "falsification_relevance": "The opposite fact falsifies H1.",
        "tool_name": "read_code",
        "arguments": {"path": "src/module.py", "start_line": 1, "end_line": 1},
    }
    provider = FakeModelProvider(
        structured_responses={
            "form_hypothesis": {"hypothesis": proposal_payload("module.h1")}
        },
        structured_response_sequences={
            "select_experiment": [select.copy() for _ in range(8)],
            "update_evidence": [
                {
                    "hypothesis_id": "H1",
                    "observation_ref": f"O{index}",
                    "direction": "inconclusive",
                    "explanation": "This fact alone is not decisive.",
                }
                for index in range(1, 9)
            ],
            "assess_hypothesis": [
                {
                    "outcome": "continue_testing",
                    "evidence_refs": [f"E{index}"],
                    "rationale": "Another discriminating Experiment is needed.",
                }
                for index in range(1, 9)
            ],
        },
    )

    result = DiagnosisApplicationService(
        provider=provider,
        run_store=RunStore(tmp_path / "runs"),
        tool_runtime=ToolRuntime(workspace, manifest, enforce_faulty_commit=False),
    ).start_diagnosis(resolved_task(valid_manifest_data))

    assert result.status == "completed"
    assert result.stop_reason == "tool_budget_exhausted"
    assert len(result.observations) == 8
    assert len(result.evidence) == 8
    assert provider.structured_calls.count("select_experiment") == 8


def test_tool_contract_failure_preserves_tool_category_without_misclassifying_run(
    tmp_path: Path, valid_manifest_data: dict[str, object]
) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "src").mkdir(parents=True)
    manifest = TaskManifest.model_validate(valid_manifest_data)
    provider = FakeModelProvider(
        {
            "form_hypothesis": {"hypothesis": proposal_payload("module.h1")},
            "select_experiment": {
                "hypothesis_id": "H1",
                "purpose": "Attempt a bounded source read.",
                "expected_observation": "A source excerpt.",
                "falsification_relevance": "The excerpt could falsify H1.",
                "tool_name": "read_code",
                "arguments": {
                    "path": "../secret.py",
                    "start_line": 1,
                    "end_line": 1,
                },
            },
        }
    )

    result = DiagnosisApplicationService(
        provider=provider,
        run_store=RunStore(tmp_path / "runs"),
        tool_runtime=ToolRuntime(workspace, manifest, enforce_faulty_commit=False),
    ).start_diagnosis(resolved_task(valid_manifest_data))

    assert result.status == "failed"
    assert result.stop_reason == "tool_failure"
    events = [json.loads(line) for line in result.events_path.read_text().splitlines()]
    assert events[-2]["tool_result"]["error_category"] == "permission_denied"
    assert events[-1]["failure_category"] is None
