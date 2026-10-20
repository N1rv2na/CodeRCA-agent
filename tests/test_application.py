from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, cast

import pytest

from coderca.application import DiagnosisApplicationService
from coderca.benchmark import load_task_1_manifest, materialize_task_1
from coderca.context_builder import DiagnosisTaskContext
from coderca.contracts import RegisteredTestCommand, TaskManifest
from coderca.model_provider import FakeModelProvider, ModelProviderError
from coderca.run_store import RunStore
from coderca.tool_runtime import ToolRuntime


def test_formation_network_failure_has_audited_request_without_response_link(
    tmp_path: Path,
    valid_manifest_data: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = FakeModelProvider()

    def fail(**kwargs: Any) -> Any:
        raise ModelProviderError("network_error", "offline")

    monkeypatch.setattr(provider, "generate_structured", fail)
    result = DiagnosisApplicationService(
        provider=provider, run_store=RunStore(tmp_path / "runs")
    ).start_diagnosis(resolved_task(valid_manifest_data))
    snapshot = json.loads(
        (
            result.run_directory / "model-requests" / "form-hypothesis-attempt-1.json"
        ).read_text()
    )
    assert snapshot["response_artifact"] is None
    assert snapshot["working_context"]


def proposal_payload(symbol: str = "package.module.select_value") -> dict[str, object]:
    return {
        "root_symbol": symbol,
        "location_description": None,
        "mechanism": "A truthiness fallback discards explicit zero.",
        "falsification_criterion": "The code distinguishes zero from missing.",
    }


def report_payload() -> dict[str, object]:
    return {
        "trigger_condition": "The configuration stores an explicit false value.",
        "propagation_path": "The truthiness branch falls through to the default path.",
        "failure_manifestation": "The registered test observes true instead of false.",
        "repair_recommendation": "Preserve explicit false values with a None check.",
        "location": None,
    }


def resolved_task(valid_manifest_data: dict[str, object]) -> DiagnosisTaskContext:
    return DiagnosisTaskContext(
        manifest=TaskManifest.model_validate(valid_manifest_data),
        ci_failure_excerpt="pytest failed: expected 1, got 2",
        ci_failure_artifact=str(valid_manifest_data["ci_log"]),
    )


def test_run_tests_experiment_flows_through_observation_evidence_and_report(
    tmp_path: Path,
    valid_manifest_data: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    source = workspace / "src" / "module.py"
    source.parent.mkdir(parents=True)
    source.write_text("value = True\n")
    manifest_data = dict(valid_manifest_data)
    manifest_data["read_paths"] = ["src/"]
    manifest_data["write_paths"] = ["src/module.py"]
    task = resolved_task(manifest_data)
    command = RegisteredTestCommand(
        schema_version="1",
        command_id="registered-tests",
        argv=("python", "-m", "pytest", "-q"),
        static_check_argv=(
            "python",
            "-c",
            "from pathlib import Path; source = Path('src/module.py').read_bytes(); "
            "compile(source, 'src/module.py', 'exec')",
        ),
        timeout_seconds=30,
    )
    provider = FakeModelProvider(
        {
            "form_hypothesis": {"hypothesis": proposal_payload("module.select")},
            "select_experiment": {
                "hypothesis_id": "H1",
                "purpose": "Run the registered failing test against H1.",
                "expected_observation": "The test reproduces the assertion failure.",
                "falsification_relevance": "A passing test would falsify H1.",
                "tool_name": "run_tests",
                "arguments": {"test_command_id": "registered-tests"},
            },
            "update_evidence": {
                "hypothesis_id": "H1",
                "observation_ref": "O1",
                "direction": "supporting",
                "explanation": "The registered test reproduces the predicted failure.",
            },
            "assess_hypothesis": {
                "outcome": "sufficiently_supported",
                "evidence_refs": ["E1"],
                "rationale": "The real test Observation supports H1.",
            },
            "generate_patch_intent": {
                "hypothesis_id": "H1",
                "target_path": "src/module.py",
                "mechanism": "Preserve explicit false values.",
                "edits": [{"old_text": "True", "new_text": "False"}],
            },
            "generate_report": report_payload(),
        }
    )

    real_run = subprocess.run

    def test_failure(
        docker_command: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        if docker_command[0] == "git":
            return cast(
                subprocess.CompletedProcess[str], real_run(docker_command, **kwargs)
            )
        del kwargs
        if any("compile(source" in item for item in docker_command):
            return subprocess.CompletedProcess(docker_command, 0, stdout="STATIC_OK\n")
        mount = docker_command[docker_command.index("--mount") + 1]
        mounted = Path(
            next(
                part.removeprefix("src=")
                for part in mount.split(",")
                if part.startswith("src=")
            )
        )
        if (mounted / "src/module.py").read_text() == "value = False\n":
            return subprocess.CompletedProcess(docker_command, 0, stdout="1 passed\n")
        return subprocess.CompletedProcess(
            docker_command,
            1,
            stdout="FAIL: test_case\nAssertionError: expected false\n",
        )

    monkeypatch.setattr("coderca.tool_runtime.subprocess.run", test_failure)
    runtime = ToolRuntime(
        workspace,
        task.manifest,
        registered_test_command=command,
        enforce_faulty_commit=False,
    )

    result = DiagnosisApplicationService(
        provider=provider,
        run_store=RunStore(tmp_path / "runs"),
        tool_runtime=runtime,
    ).start_diagnosis(task)

    assert result.status == "completed"
    assert result.hypothesis_history[0].status == "supported"
    assert result.observations[0].source == "run_tests"
    assert result.observations[0].tool_result_ref == "T1"
    assert "exit_code: 1" in result.observations[0].excerpt
    assert result.evidence[0].provenance == "run_tests:tool-results/T1.txt"
    artifact = result.run_directory / result.observations[0].artifact_ref
    assert "AssertionError: expected false" in artifact.read_text()
    events = [json.loads(line) for line in result.events_path.read_text().splitlines()]
    tool_event = next(item for item in events if item["event_type"] == "tool_executed")
    assert tool_event["experiment"]["tool_name"] == "run_tests"
    assert tool_event["tool_result"]["command_id"] == "registered-tests"
    assert tool_event["tool_result"]["exit_code"] == 1


@pytest.mark.parametrize(
    ("test_exit_code", "expected_validation_status", "expected_stop_reason"),
    [(0, "passed", "validation_passed"), (1, "failed", "validation_failed")],
)
def test_supported_hypothesis_generates_one_patch_and_finalizes_after_validation(
    tmp_path: Path,
    valid_manifest_data: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
    test_exit_code: int,
    expected_validation_status: str,
    expected_stop_reason: str,
) -> None:
    workspace = tmp_path / "workspace"
    source = workspace / "src" / "module.py"
    source.parent.mkdir(parents=True)
    source.write_text("value = True\n")
    manifest_data = dict(valid_manifest_data)
    manifest_data["read_paths"] = ["src/"]
    manifest_data["write_paths"] = ["src/module.py"]
    task = resolved_task(manifest_data)
    command = RegisteredTestCommand(
        schema_version="1",
        command_id=str(manifest_data["test_command_id"]),
        argv=("python", "-m", "pytest", "-q"),
        static_check_argv=(
            "python",
            "-c",
            "from pathlib import Path; source = Path('src/module.py').read_bytes(); "
            "compile(source, 'src/module.py', 'exec')",
        ),
        timeout_seconds=30,
    )
    provider = FakeModelProvider(
        {
            "form_hypothesis": {"hypothesis": proposal_payload("module.value")},
            "select_experiment": {
                "hypothesis_id": "H1",
                "purpose": "Read the faulty value.",
                "expected_observation": "The value is true.",
                "falsification_relevance": "A false value would falsify H1.",
                "tool_name": "read_code",
                "arguments": {"path": "src/module.py", "start_line": 1, "end_line": 1},
            },
            "update_evidence": {
                "hypothesis_id": "H1",
                "observation_ref": "O1",
                "direction": "supporting",
                "explanation": "The source contains the faulty truthy value.",
            },
            "assess_hypothesis": {
                "outcome": "sufficiently_supported",
                "evidence_refs": ["E1"],
                "rationale": "E1 supports H1.",
            },
            "generate_patch_intent": {
                "hypothesis_id": "H1",
                "target_path": "src/module.py",
                "mechanism": "Preserve the false value.",
                "edits": [{"old_text": "True", "new_text": "False"}],
            },
            "generate_report": report_payload(),
        }
    )
    real_run = subprocess.run

    def run(command_line: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if command_line[0] == "git":
            return cast(
                subprocess.CompletedProcess[str], real_run(command_line, **kwargs)
            )
        mount = command_line[command_line.index("--mount") + 1]
        mounted = Path(
            next(
                part.removeprefix("src=")
                for part in mount.split(",")
                if part.startswith("src=")
            )
        )
        assert (mounted / "src/module.py").read_text() == "value = False\n"
        if any("compile(source" in item for item in command_line):
            return subprocess.CompletedProcess(command_line, 0, stdout="STATIC_OK\n")
        return subprocess.CompletedProcess(
            command_line,
            test_exit_code,
            stdout="1 passed\n" if test_exit_code == 0 else "1 failed\n",
        )

    monkeypatch.setattr("coderca.tool_runtime.subprocess.run", run)
    runtime = ToolRuntime(
        workspace,
        task.manifest,
        registered_test_command=command,
        enforce_faulty_commit=False,
    )

    result = DiagnosisApplicationService(
        provider=provider,
        run_store=RunStore(tmp_path / "runs"),
        tool_runtime=runtime,
    ).start_diagnosis(task)

    assert result.status == "completed"
    assert result.stage == "finalizing"
    assert result.stop_reason == expected_stop_reason
    assert result.patch is not None
    assert result.validation is not None
    assert result.validation.status == expected_validation_status
    assert result.root_cause_analysis is not None
    assert result.root_cause_analysis.trigger_condition.startswith("The configuration")
    assert [item.source for item in result.observations] == [
        "read_code",
        "public_validation",
    ]
    assert result.observations[-1].experiment_id is None
    assert result.observations[-1].validation_action_id == "V1"
    assert result.observations[-1].tool_result_ref == "T2"
    assert [item.direction for item in result.evidence] == [
        "supporting",
        "supporting" if expected_validation_status == "passed" else "inconclusive",
    ]
    assert provider.structured_calls.count("generate_patch_intent") == 1
    assert provider.structured_calls[-2:] == [
        "generate_patch_intent",
        "generate_report",
    ]
    assert source.read_text() == "value = True\n"
    report = json.loads(result.report_path.read_text())
    assert report["patch"]["hypothesis_id"] == "H1"
    assert report["validation"]["status"] == expected_validation_status
    assert report["root_cause_analysis"] == report_payload()
    assert (result.run_directory / report["validation"]["patch_artifact_ref"]).is_file()
    assert (result.run_directory / report["validation"]["artifact_ref"]).is_file()
    events = [json.loads(line) for line in result.events_path.read_text().splitlines()]
    assert sum(event["event_type"] == "patch_generated" for event in events) == 1
    assert sum(event["event_type"] == "validation_completed" for event in events) == 1
    assert sum(event["event_type"] == "report_generated" for event in events) == 1
    validation_event = next(
        event for event in events if event["event_type"] == "validation_completed"
    )
    assert validation_event["validation_action"]["validation_action_id"] == "V1"
    assert validation_event["tool_result"]["validation_action_id"] == "V1"
    assert validation_event["experiment"] is None
    assert events[-1]["event_type"] == "run_completed"
    assert not any(
        event["stage"] == "diagnosing"
        for event in events
        if event["sequence"]
        > next(
            item["sequence"]
            for item in events
            if item["event_type"] == "validation_completed"
        )
    )


@pytest.mark.parametrize("corrected", [True, False])
def test_patch_intent_compilation_uses_one_bounded_correction_before_candidate(
    tmp_path: Path,
    valid_manifest_data: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
    corrected: bool,
) -> None:
    workspace = tmp_path / "workspace"
    source = workspace / "src" / "module.py"
    source.parent.mkdir(parents=True)
    source.write_text("value = True\n")
    manifest_data = dict(valid_manifest_data)
    manifest_data["read_paths"] = ["src/"]
    manifest_data["write_paths"] = ["src/module.py"]
    task = resolved_task(manifest_data)
    command = RegisteredTestCommand(
        schema_version="1",
        command_id=str(manifest_data["test_command_id"]),
        argv=("python", "-m", "pytest", "-q"),
        static_check_argv=("python", "-m", "compileall", "-q", "src"),
        timeout_seconds=30,
    )
    invalid_intent = {
        "hypothesis_id": "H1",
        "target_path": "src/module.py",
        "mechanism": "Replace a missing source fragment.",
        "edits": [{"old_text": "missing", "new_text": "False"}],
    }
    valid_intent = {
        "hypothesis_id": "H1",
        "target_path": "src/module.py",
        "mechanism": "Preserve the false value.",
        "edits": [{"old_text": "True", "new_text": "False"}],
    }
    provider = FakeModelProvider(
        structured_responses={
            "form_hypothesis": {"hypothesis": proposal_payload("module.value")},
            "select_experiment": {
                "hypothesis_id": "H1",
                "purpose": "Read the faulty value.",
                "expected_observation": "The value is true.",
                "falsification_relevance": "A false value would falsify H1.",
                "tool_name": "read_code",
                "arguments": {"path": "src/module.py", "start_line": 1, "end_line": 1},
            },
            "update_evidence": {
                "hypothesis_id": "H1",
                "observation_ref": "O1",
                "direction": "supporting",
                "explanation": "The source contains the faulty truthy value.",
            },
            "assess_hypothesis": {
                "outcome": "sufficiently_supported",
                "evidence_refs": ["E1"],
                "rationale": "E1 supports H1.",
            },
            "generate_report": report_payload(),
        },
        structured_response_sequences={
            "generate_patch_intent": [
                invalid_intent,
                valid_intent if corrected else invalid_intent,
            ]
        },
    )
    real_run = subprocess.run

    def run(command_line: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if command_line[0] == "git":
            return cast(
                subprocess.CompletedProcess[str], real_run(command_line, **kwargs)
            )
        return subprocess.CompletedProcess(command_line, 0, stdout="PASS\n")

    monkeypatch.setattr("coderca.tool_runtime.subprocess.run", run)
    result = DiagnosisApplicationService(
        provider=provider,
        run_store=RunStore(tmp_path / "runs"),
        tool_runtime=ToolRuntime(
            workspace,
            task.manifest,
            registered_test_command=command,
            enforce_faulty_commit=False,
        ),
    ).start_diagnosis(task)

    assert provider.structured_calls.count("generate_patch_intent") == 2
    events = [json.loads(line) for line in result.events_path.read_text().splitlines()]
    corrections = [
        event
        for event in events
        if event["event_type"] == "schema_correction_requested"
        and "generate_patch_intent" in event["message"]
    ]
    assert len(corrections) == 1
    assert corrections[0]["validation_errors"][0]["type"] == "missing_match"
    corrected_request = next(
        request
        for request in provider.structured_requests[1:]
        if request["schema_name"] == "generate_patch_intent"
        and "schema_correction" in json.loads(request["user_prompt"])
    )
    assert json.loads(corrected_request["user_prompt"])["schema_correction"]

    if corrected:
        assert result.stop_reason == "validation_passed"
        assert result.patch is not None
        assert sum(event["event_type"] == "patch_generated" for event in events) == 1
        assert (
            sum(event["event_type"] == "validation_completed" for event in events)
            == 1
        )
    else:
        assert result.status == "failed"
        assert result.stop_reason == "schema_failure"
        assert result.patch is None
        assert not any(event["event_type"] == "patch_generated" for event in events)
        assert not any(
            event["event_type"] == "validation_completed" for event in events
        )


def test_supported_hypothesis_does_not_patch_after_tool_budget_is_exhausted(
    tmp_path: Path,
    valid_manifest_data: dict[str, object],
) -> None:
    workspace = tmp_path / "workspace"
    source = workspace / "src" / "module.py"
    source.parent.mkdir(parents=True)
    source.write_text("value = True\n")
    manifest_data = dict(valid_manifest_data)
    manifest_data.update(
        {
            "read_paths": ["src/"],
            "write_paths": ["src/module.py"],
            "tool_call_limit": 1,
        }
    )
    task = resolved_task(manifest_data)
    command = RegisteredTestCommand(
        schema_version="1",
        command_id=str(manifest_data["test_command_id"]),
        argv=("python", "-m", "pytest", "-q"),
        static_check_argv=("python", "-m", "compileall", "-q", "src"),
        timeout_seconds=30,
    )
    provider = FakeModelProvider(
        {
            "form_hypothesis": {"hypothesis": proposal_payload("module.value")},
            "select_experiment": {
                "hypothesis_id": "H1",
                "purpose": "Read the faulty value.",
                "expected_observation": "The value is true.",
                "falsification_relevance": "A false value would falsify H1.",
                "tool_name": "read_code",
                "arguments": {"path": "src/module.py", "start_line": 1, "end_line": 1},
            },
            "update_evidence": {
                "hypothesis_id": "H1",
                "observation_ref": "O1",
                "direction": "supporting",
                "explanation": "The source contains the faulty value.",
            },
            "assess_hypothesis": {
                "outcome": "sufficiently_supported",
                "evidence_refs": ["E1"],
                "rationale": "E1 supports H1.",
            },
        }
    )
    runtime = ToolRuntime(
        workspace,
        task.manifest,
        registered_test_command=command,
        enforce_faulty_commit=False,
    )

    result = DiagnosisApplicationService(
        provider=provider,
        run_store=RunStore(tmp_path / "runs"),
        tool_runtime=runtime,
    ).start_diagnosis(task)

    assert result.stop_reason == "tool_budget_exhausted"
    assert result.patch is None
    assert result.validation is None
    assert "generate_patch_intent" not in provider.structured_calls


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
            "used_experiment_budget": 0,
            "remaining_experiment_budget": 3,
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


def test_search_code_flows_through_existing_observation_and_evidence_pipeline(
    tmp_path: Path, valid_manifest_data: dict[str, object]
) -> None:
    workspace = tmp_path / "workspace"
    source = workspace / "src" / "flags.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "def is_active(value):\n    return value or True\n",
        encoding="utf-8",
    )
    manifest_data = dict(valid_manifest_data)
    manifest_data["read_paths"] = ["src/"]
    task = resolved_task(manifest_data)
    provider = FakeModelProvider(
        {
            "form_hypothesis": {"hypothesis": proposal_payload("flags.is_active")},
            "select_experiment": {
                "hypothesis_id": "H1",
                "purpose": "Find the implementation named by H1.",
                "expected_observation": "The source contains is_active.",
                "falsification_relevance": (
                    "No implementation match would weaken the proposed location."
                ),
                "tool_name": "search_code",
                "arguments": {
                    "query": "is_active",
                    "search_kind": "content",
                    "max_results": 5,
                    "context_lines": 1,
                },
            },
            "update_evidence": {
                "hypothesis_id": "H1",
                "observation_ref": "O1",
                "direction": "supporting",
                "explanation": (
                    "The bounded search Observation locates the predicted function."
                ),
            },
            "assess_hypothesis": {
                "outcome": "sufficiently_supported",
                "evidence_refs": ["E1"],
                "rationale": "E1 links H1 to repository code.",
            },
        }
    )
    runtime = ToolRuntime(
        workspace,
        task.manifest,
        enforce_faulty_commit=False,
    )

    result = DiagnosisApplicationService(
        provider=provider,
        run_store=RunStore(tmp_path / "runs"),
        tool_runtime=runtime,
    ).start_diagnosis(task)

    assert result.status == "completed"
    assert result.stop_reason == "read_only_diagnosis_complete"
    assert result.observations[0].source == "search_code"
    assert result.observations[0].tool_result_ref == "T1"
    assert '"status": "matched"' in result.observations[0].excerpt
    assert result.evidence[0].observation_ref == "O1"
    assert result.evidence[0].provenance == "search_code:tool-results/T1.txt"
    assert (result.run_directory / "tool-results/T1.txt").is_file()
    select_request = next(
        request
        for request in provider.structured_requests
        if request["schema_name"] == "select_experiment"
    )
    select_context = json.loads(select_request["user_prompt"])
    assert "search_code" in {tool["name"] for tool in select_context["available_tools"]}


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
    assert "read_code" in {tool["name"] for tool in context["available_tools"]}
    assert "testable with available_tools" in reformulation_request["system_prompt"]
    assert "if self.everyone" not in reformulation_request["user_prompt"]
    h2_update_request = next(
        request
        for request in provider.structured_requests
        if request["schema_name"] == "update_evidence"
        and json.loads(request["user_prompt"])["active_hypothesis"][
            "hypothesis_id"
        ]
        == "H2"
    )
    h2_update_context = json.loads(h2_update_request["user_prompt"])
    assert [
        item["evidence_id"]
        for item in h2_update_context["evidence_basis_knowledge"]["evidence"]
    ] == ["E1"]
    assert h2_update_context["existing_relevant_evidence"] == []
    assert "Evidence Basis Knowledge" in h2_update_request["system_prompt"]
    h2_assessment_request = next(
        request
        for request in provider.structured_requests
        if request["schema_name"] == "assess_hypothesis"
        and json.loads(request["user_prompt"])["active_hypothesis"][
            "hypothesis_id"
        ]
        == "H2"
    )
    h2_assessment_context = json.loads(h2_assessment_request["user_prompt"])
    assert [
        item["evidence_id"]
        for item in h2_assessment_context["evidence_basis_knowledge"]["evidence"]
    ] == ["E1"]
    assert [
        item["evidence_id"] for item in h2_assessment_context["relevant_evidence"]
    ] == ["E2"]
    assert "Evidence Basis Knowledge" in h2_assessment_request["system_prompt"]


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
    snapshots = [
        json.loads(p.read_text())
        for p in (result.run_directory / "model-requests").glob("*.json")
    ]
    updates = [s for s in snapshots if s["decision_type"] == "update_evidence"]
    assert len(updates) == 2
    assert sorted(s["attempt"] for s in updates) == [1, 2]
    assert all("response_schema" in s for s in updates)
    assert all("uninspected" in s["system_prompt"] for s in updates)
    assert all(
        "relative to the Active Hypothesis mechanism" in s["system_prompt"]
        for s in updates
    )
    assert all(
        "concrete alternative mechanism" in s["system_prompt"] for s in updates
    )
    assessment_requests = [
        r
        for r in provider.structured_requests
        if r["schema_name"] == "assess_hypothesis"
    ]
    assessment_prompt = assessment_requests[0]["system_prompt"]
    assert "Do not relabel" in assessment_prompt
    assert (
        "feasible non-redundant Experiment" in assessment_prompt
    )
    assert (
        "exactly these three keys: outcome, evidence_refs, rationale"
        in assessment_prompt
    )
    assert '"outcome": "continue_testing"' in assessment_prompt
    assert '"evidence_refs": ["E1"]' in assessment_prompt
    assert '"rationale": "Explain the assessment from registered Evidence."' in (
        assessment_prompt
    )
    assert "note fields" not in assessment_prompt
    select_requests = [
        r
        for r in provider.structured_requests
        if r["schema_name"] == "select_experiment"
    ]
    assert "observation_capabilities" in select_requests[0]["system_prompt"]
    assert "instrumentation" in select_requests[0]["system_prompt"]
    assert all(
        (result.run_directory / s["response_artifact"]).is_file() for s in updates
    )
    events = [json.loads(line) for line in result.events_path.read_text().splitlines()]
    assert any(event["event_type"] == "schema_correction_requested" for event in events)


def test_unknown_tool_selection_is_corrected_before_budget_or_runtime_execution(
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
                    "falsification_criterion": "The diff preserves a None check.",
                }
            },
            "update_evidence": {
                "hypothesis_id": "H1",
                "observation_ref": "O1",
                "direction": "supporting",
                "explanation": "The diff contains the predicted guard change.",
            },
            "assess_hypothesis": {
                "outcome": "sufficiently_supported",
                "evidence_refs": ["E1"],
                "rationale": "The registered diff Evidence supports H1.",
            },
        },
        structured_response_sequences={
            "select_experiment": [
                {
                    "hypothesis_id": "H1",
                    "purpose": "Instrument and execute the failing test.",
                    "expected_observation": "The runtime value is printed.",
                    "falsification_relevance": "A false value falsifies H1.",
                    "tool_name": "run_test_with_instrumentation",
                    "arguments": {"test_selector": "test_case_17"},
                },
                {
                    "hypothesis_id": "H1",
                    "purpose": "Inspect the Faulty Commit diff.",
                    "expected_observation": "The boolean guard changed.",
                    "falsification_relevance": "No guard change falsifies H1.",
                    "tool_name": "inspect_diff",
                    "arguments": {"path": "waffle/models.py"},
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
    assert result.stop_reason == "read_only_diagnosis_complete"
    assert provider.structured_calls.count("select_experiment") == 2
    select_requests = [
        request
        for request in provider.structured_requests
        if request["schema_name"] == "select_experiment"
    ]
    first_context = json.loads(select_requests[0]["user_prompt"])
    corrected_context = json.loads(select_requests[1]["user_prompt"])
    assert [item["name"] for item in first_context["available_tools"]] == [
        "inspect_diff",
        "read_code",
        "search_code",
    ]
    assert corrected_context["schema_correction"]["validation_errors"][0]["loc"] == [
        "tool_name"
    ]
    events = [json.loads(line) for line in result.events_path.read_text().splitlines()]
    tool_events = [event for event in events if event["event_type"] == "tool_executed"]
    assert len(tool_events) == 1
    assert tool_events[0]["experiment"]["experiment_id"] == "X1"
    assert tool_events[0]["experiment"]["tool_name"] == "inspect_diff"
    assert tool_events[0]["tool_result"]["tool_result_id"] == "T1"


def test_second_unknown_tool_selection_fails_without_runtime_execution(
    tmp_path: Path,
) -> None:
    manifest = load_task_1_manifest()
    workspace = materialize_task_1(tmp_path / "workspace")
    task = DiagnosisTaskContext(
        manifest=manifest,
        ci_failure_excerpt="AssertionError: True is not false",
        ci_failure_artifact=manifest.ci_log,
    )
    invalid_selection = {
        "hypothesis_id": "H1",
        "purpose": "Instrument and execute the failing test.",
        "expected_observation": "The runtime value is printed.",
        "falsification_relevance": "A false value falsifies H1.",
        "tool_name": "run_test_with_instrumentation",
        "arguments": {"test_selector": "test_case_17"},
    }
    provider = FakeModelProvider(
        structured_responses={
            "form_hypothesis": {"hypothesis": proposal_payload("module.h1")}
        },
        structured_response_sequences={
            "select_experiment": [invalid_selection, invalid_selection]
        },
    )

    result = DiagnosisApplicationService(
        provider=provider,
        run_store=RunStore(tmp_path / "runs"),
        tool_runtime=ToolRuntime(workspace, manifest),
    ).start_diagnosis(task)

    assert result.status == "failed"
    assert result.stop_reason == "schema_failure"
    assert result.observations == ()
    assert result.evidence == ()
    assert provider.structured_calls.count("select_experiment") == 2
    events = [json.loads(line) for line in result.events_path.read_text().splitlines()]
    assert (
        sum(event["event_type"] == "schema_correction_requested" for event in events)
        == 1
    )
    assert not any(event["event_type"] == "tool_executed" for event in events)
    assert not (result.run_directory / "tool-results").exists()


def test_observation_id_in_assessment_is_corrected_before_state_mutation(
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
                    "falsification_criterion": "The diff preserves a None check.",
                }
            },
            "select_experiment": {
                "hypothesis_id": "H1",
                "purpose": "Inspect the Faulty Commit diff.",
                "expected_observation": "The boolean guard changed.",
                "falsification_relevance": "No guard change falsifies H1.",
                "tool_name": "inspect_diff",
                "arguments": {"path": "waffle/models.py"},
            },
            "update_evidence": {
                "hypothesis_id": "H1",
                "observation_ref": "O1",
                "direction": "supporting",
                "explanation": "The diff contains the predicted guard change.",
            },
        },
        structured_response_sequences={
            "assess_hypothesis": [
                {
                    "outcome": "sufficiently_supported",
                    "evidence_refs": ["E1", "O1"],
                    "rationale": "The diff and its Observation support H1.",
                },
                {
                    "outcome": "sufficiently_supported",
                    "evidence_refs": ["E1"],
                    "rationale": "The registered Evidence E1 supports H1.",
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
    assert result.stop_reason == "read_only_diagnosis_complete"
    assert result.hypothesis_history[0].status == "supported"
    assert provider.structured_calls.count("assess_hypothesis") == 2
    assessment_requests = [
        request
        for request in provider.structured_requests
        if request["schema_name"] == "assess_hypothesis"
    ]
    corrected_context = json.loads(assessment_requests[1]["user_prompt"])
    error = corrected_context["schema_correction"]["validation_errors"][0]
    assert error["loc"] == ["evidence_refs", 1]
    assert error["input"] == "O1"
    assert error["allowed_evidence_ids"] == ["E1"]
    events = [json.loads(line) for line in result.events_path.read_text().splitlines()]
    assert (
        len([event for event in events if event["event_type"] == "tool_executed"]) == 1
    )
    assert (
        len([event for event in events if event["event_type"] == "evidence_recorded"])
        == 1
    )


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


def test_three_experiments_force_terminal_assessment_before_a_fourth_execution(
    tmp_path: Path, valid_manifest_data: dict[str, object]
) -> None:
    workspace = tmp_path / "workspace"
    source = workspace / "src" / "module.py"
    source.parent.mkdir(parents=True)
    source.write_text("value = 1\n")
    manifest = TaskManifest.model_validate(
        {**valid_manifest_data, "tool_call_limit": 3}
    )
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
            "select_experiment": [select.copy() for _ in range(3)],
            "update_evidence": [
                {
                    "hypothesis_id": "H1",
                    "observation_ref": f"O{index}",
                    "direction": "inconclusive",
                    "explanation": "This fact alone is not decisive.",
                }
                for index in range(1, 4)
            ],
            "assess_hypothesis": [
                {
                    "outcome": "continue_testing",
                    "evidence_refs": [f"E{index}"],
                    "rationale": "Another discriminating Experiment is needed.",
                }
                for index in range(1, 4)
            ]
            + [
                {
                    "outcome": "inconclusive",
                    "evidence_refs": ["E3"],
                    "rationale": "The per-Hypothesis Experiment budget is exhausted.",
                }
            ],
            "reformulate_hypothesis": [
                {
                    "hypothesis": {
                        **proposal_payload("module.h2"),
                        "mechanism": "A materially different second mechanism.",
                    },
                    "evidence_refs": ["E3"],
                }
            ],
        },
    )

    result = DiagnosisApplicationService(
        provider=provider,
        run_store=RunStore(tmp_path / "runs"),
        tool_runtime=ToolRuntime(workspace, manifest, enforce_faulty_commit=False),
    ).start_diagnosis(
        DiagnosisTaskContext(
            manifest=manifest,
            ci_failure_excerpt="AssertionError",
            ci_failure_artifact=manifest.ci_log,
        )
    )

    assert result.status == "completed"
    assert result.stop_reason == "tool_budget_exhausted"
    assert len(result.observations) == 3
    assert len(result.evidence) == 3
    assert provider.structured_calls.count("select_experiment") == 3
    assert provider.structured_calls.count("assess_hypothesis") == 4
    assert result.hypothesis_history[0].status == "inconclusive"


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
