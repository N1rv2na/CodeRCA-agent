from __future__ import annotations

import json
from pathlib import Path

from coderca.application import DiagnosisApplicationService
from coderca.contracts import TaskManifest
from coderca.model_provider import FakeModelProvider
from coderca.run_store import RunStore


def test_start_diagnosis_creates_terminal_result_and_parseable_artifacts(
    tmp_path: Path, valid_manifest_data: dict[str, object]
) -> None:
    manifest = TaskManifest.model_validate(valid_manifest_data)
    service = DiagnosisApplicationService(
        provider=FakeModelProvider(), run_store=RunStore(tmp_path / "runs")
    )

    result = service.start_diagnosis(manifest)

    assert result.stage == "finalizing"
    assert result.status == "completed"
    assert result.stop_reason == "fake_model_completed"
    assert result.task_id == "task-001"
    assert result.run_directory.is_dir()

    manifest_snapshot = json.loads(result.manifest_path.read_text())
    assert manifest_snapshot == valid_manifest_data
    events = [json.loads(line) for line in result.events_path.read_text().splitlines()]
    assert events
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
    report = json.loads(result.report_path.read_text())
    assert report["stage"] == "finalizing"
    assert report["status"] == "completed"
    assert report["stop_reason"] == "fake_model_completed"


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
