from __future__ import annotations

import json
from pathlib import Path

import pytest

from coderca.application import DiagnosisApplicationService
from coderca.contracts import TaskManifest
from coderca.model_provider import FakeModelProvider
from coderca.run_store import RunStore


def hypothesis_payload(symbol: str) -> dict[str, object]:
    return {
        "root_symbol": symbol,
        "location_description": None,
        "mechanism": "A truthiness fallback discards explicit zero.",
        "falsification_criterion": "The code distinguishes zero from missing.",
    }


def test_start_diagnosis_forms_hypotheses_and_persists_observable_artifacts(
    tmp_path: Path, valid_manifest_data: dict[str, object]
) -> None:
    manifest = TaskManifest.model_validate(valid_manifest_data)
    provider = FakeModelProvider(
        {
            "form_hypotheses": {
                "hypotheses": [
                    {
                        "root_symbol": "package.module.select_value",
                        "location_description": None,
                        "mechanism": "A truthiness fallback discards explicit zero.",
                        "falsification_criterion": (
                            "The implementation distinguishes zero from missing."
                        ),
                    }
                ]
            }
        }
    )
    service = DiagnosisApplicationService(
        provider=provider, run_store=RunStore(tmp_path / "runs")
    )

    result = service.start_diagnosis(manifest)

    assert result.stage == "diagnosing"
    assert result.status == "in_progress"
    assert result.stop_reason is None
    assert result.task_id == "task-001"
    assert [item.hypothesis_id for item in result.hypotheses] == ["H1"]
    assert result.hypotheses[0].root_symbol == "package.module.select_value"
    assert result.run_directory.is_dir()
    assert provider.structured_calls == ["form_hypotheses"]

    manifest_snapshot = json.loads(result.manifest_path.read_text())
    assert manifest_snapshot == valid_manifest_data
    events = [json.loads(line) for line in result.events_path.read_text().splitlines()]
    assert [event["stage"] for event in events] == [
        "preparing",
        "forming_hypotheses",
        "diagnosing",
    ]
    assert events[-1]["event_type"] == "hypotheses_formed"
    assert events[-1]["hypotheses"][0]["hypothesis_id"] == "H1"
    response_path = result.run_directory / events[-1]["model_response_artifact"]
    assert json.loads(response_path.read_text()) == {
        "hypotheses": [
            {
                "falsification_criterion": (
                    "The implementation distinguishes zero from missing."
                ),
                "location_description": None,
                "mechanism": "A truthiness fallback discards explicit zero.",
                "root_symbol": "package.module.select_value",
            }
        ]
    }
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
    report = json.loads(result.report_path.read_text())
    assert report["stage"] == "diagnosing"
    assert report["status"] == "in_progress"
    assert report["stop_reason"] is None
    assert report["hypotheses"][0]["hypothesis_id"] == "H1"


def test_two_diagnosis_runs_use_distinct_directories(
    tmp_path: Path, valid_manifest_data: dict[str, object]
) -> None:
    manifest = TaskManifest.model_validate(valid_manifest_data)
    service = DiagnosisApplicationService(
        provider=FakeModelProvider(), run_store=RunStore(tmp_path / "runs")
    )

    first = service.start_diagnosis(manifest)
    second = service.start_diagnosis(manifest)

    assert first.run_id != second.run_id
    assert first.run_directory != second.run_directory
    assert first.run_directory.is_dir()
    assert second.run_directory.is_dir()


def test_first_invalid_formation_gets_one_fresh_bounded_correction_request(
    tmp_path: Path, valid_manifest_data: dict[str, object]
) -> None:
    oversized_log = "failure-line\n" * 1_000
    manifest = TaskManifest.model_validate(
        {**valid_manifest_data, "ci_log": oversized_log}
    )
    invalid_response: dict[str, object] = {"hypotheses": []}
    valid_response = {"hypotheses": [hypothesis_payload("package.module.select_value")]}
    provider = FakeModelProvider(
        structured_response_sequences={
            "form_hypotheses": [invalid_response, valid_response]
        }
    )
    service = DiagnosisApplicationService(
        provider=provider, run_store=RunStore(tmp_path / "runs")
    )

    result = service.start_diagnosis(manifest)

    assert result.stage == "diagnosing"
    assert result.status == "in_progress"
    assert provider.structured_calls == ["form_hypotheses", "form_hypotheses"]
    assert len(provider.structured_requests) == 2
    first_context = json.loads(provider.structured_requests[0]["user_prompt"])
    second_context = json.loads(provider.structured_requests[1]["user_prompt"])
    for context in (first_context, second_context):
        failure = context["diagnosis_task"]["ci_failure"]
        assert len(failure["excerpt"]) == 2_000
        assert failure["truncated"] is True
        assert context["diagnosis_state"] == {
            "hypotheses": [],
            "stage": "forming_hypotheses",
        }
        task_context = context["diagnosis_task"]
        assert task_context["base_snapshot"] == valid_manifest_data["base_snapshot"]
        assert task_context["execution_boundary"] == {
            "docker_image": valid_manifest_data["docker_image"],
            "read_paths": valid_manifest_data["read_paths"],
            "remaining_tool_calls": valid_manifest_data["tool_call_limit"],
            "write_paths": valid_manifest_data["write_paths"],
        }
        assert "history" not in context
        assert json.dumps(invalid_response) not in json.dumps(context)
    assert "schema_correction" not in first_context
    assert second_context["schema_correction"]["attempt"] == 2
    assert second_context["schema_correction"]["failure_category"] == (
        "schema_mismatch"
    )

    events = [json.loads(line) for line in result.events_path.read_text().splitlines()]
    assert [event["sequence"] for event in events] == [1, 2, 3, 4]
    correction = events[2]
    assert correction["event_type"] == "schema_correction_requested"
    assert correction["stage"] == "forming_hypotheses"
    assert correction["failure_category"] == "schema_mismatch"
    assert correction["validation_errors"]
    assert (
        json.loads(
            (result.run_directory / correction["model_response_artifact"]).read_text()
        )
        == invalid_response
    )
    assert events[3]["event_type"] == "hypotheses_formed"


def test_second_invalid_formation_finalizes_as_schema_failure(
    tmp_path: Path, valid_manifest_data: dict[str, object]
) -> None:
    invalid_responses = [
        {"hypotheses": []},
        {
            "hypotheses": [
                hypothesis_payload(f"package.module.function_{index}")
                for index in range(1, 5)
            ]
        },
    ]
    provider = FakeModelProvider(
        structured_response_sequences={"form_hypotheses": invalid_responses}
    )
    service = DiagnosisApplicationService(
        provider=provider, run_store=RunStore(tmp_path / "runs")
    )

    result = service.start_diagnosis(TaskManifest.model_validate(valid_manifest_data))

    assert result.stage == "finalizing"
    assert result.status == "failed"
    assert result.stop_reason == "schema_failure"
    assert result.hypotheses == ()
    assert provider.structured_calls == ["form_hypotheses", "form_hypotheses"]
    events = [json.loads(line) for line in result.events_path.read_text().splitlines()]
    assert events[-1]["event_type"] == "run_failed"
    assert events[-1]["stage"] == "finalizing"
    assert events[-1]["failure_category"] == "schema_failure"
    assert events[-1]["validation_errors"]
    assert (
        json.loads(
            (result.run_directory / events[-1]["model_response_artifact"]).read_text()
        )
        == invalid_responses[1]
    )
    report = json.loads(result.report_path.read_text())
    assert report["stage"] == "finalizing"
    assert report["status"] == "failed"
    assert report["stop_reason"] == "schema_failure"
    assert report["hypotheses"] == []


@pytest.mark.parametrize("count", [1, 3])
def test_fake_provider_application_path_accepts_each_legal_candidate_boundary(
    count: int, tmp_path: Path, valid_manifest_data: dict[str, object]
) -> None:
    provider = FakeModelProvider(
        {
            "form_hypotheses": {
                "hypotheses": [
                    hypothesis_payload(f"package.module.function_{index}")
                    for index in range(1, count + 1)
                ]
            }
        }
    )

    result = DiagnosisApplicationService(
        provider=provider, run_store=RunStore(tmp_path / "runs")
    ).start_diagnosis(TaskManifest.model_validate(valid_manifest_data))

    assert [item.hypothesis_id for item in result.hypotheses] == [
        f"H{index}" for index in range(1, count + 1)
    ]


def test_field_invalid_formation_receives_one_correction_then_schema_failure(
    tmp_path: Path, valid_manifest_data: dict[str, object]
) -> None:
    field_invalid = {
        "hypotheses": [
            {
                "root_symbol": None,
                "location_description": None,
                "mechanism": "A candidate without a location.",
                "falsification_criterion": "Inspect the relevant code.",
            }
        ]
    }
    provider = FakeModelProvider(
        structured_response_sequences={
            "form_hypotheses": [field_invalid, field_invalid]
        }
    )

    result = DiagnosisApplicationService(
        provider=provider, run_store=RunStore(tmp_path / "runs")
    ).start_diagnosis(TaskManifest.model_validate(valid_manifest_data))

    assert result.stop_reason == "schema_failure"
    assert provider.structured_calls == ["form_hypotheses", "form_hypotheses"]
