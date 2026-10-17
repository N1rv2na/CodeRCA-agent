from __future__ import annotations

import json
from pathlib import Path

from coderca.application import DiagnosisApplicationService
from coderca.context_builder import DiagnosisTaskContext
from coderca.contracts import TaskManifest
from coderca.model_provider import FakeModelProvider
from coderca.run_store import RunStore


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
    assert json.loads(response_path.read_text()) == {
        "hypothesis": proposal_payload()
    }
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
