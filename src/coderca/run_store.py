"""Ordinary-file persistence for one Diagnosis Run directory."""

from __future__ import annotations

import json
from pathlib import Path

from .contracts import DiagnosisEvent, DiagnosisReport, RunArtifacts, TaskManifest
from .model_provider import PersistenceSafeModelArtifact


class RunStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def create_run(self, run_id: str) -> RunArtifacts:
        if not run_id or Path(run_id).name != run_id:
            raise ValueError("run_id must be a non-empty directory name")
        run_directory = self.root / run_id
        run_directory.mkdir(parents=True, exist_ok=False)
        return RunArtifacts(
            run_directory=run_directory,
            manifest_path=run_directory / "manifest.json",
            events_path=run_directory / "events.jsonl",
            report_path=run_directory / "report.json",
            model_responses_directory=run_directory / "model-responses",
        )

    def write_manifest(self, artifacts: RunArtifacts, manifest: TaskManifest) -> None:
        self._write_json(artifacts.manifest_path, manifest.model_dump(mode="json"))

    def write_events(
        self, artifacts: RunArtifacts, events: list[DiagnosisEvent]
    ) -> None:
        artifacts.events_path.write_text(
            "".join(
                json.dumps(event.model_dump(mode="json"), sort_keys=True) + "\n"
                for event in events
            ),
            encoding="utf-8",
        )

    def write_report(self, artifacts: RunArtifacts, report: DiagnosisReport) -> None:
        self._write_json(artifacts.report_path, report.model_dump(mode="json"))

    def write_hypothesis_formation_response(
        self,
        artifacts: RunArtifacts,
        *,
        attempt: int,
        response: PersistenceSafeModelArtifact,
    ) -> str:
        if attempt not in (1, 2):
            raise ValueError("Hypothesis formation attempt must be 1 or 2")
        artifacts.model_responses_directory.mkdir(parents=True, exist_ok=True)
        path = (
            artifacts.model_responses_directory
            / f"form-hypothesis-attempt-{attempt}.json"
        )
        self._write_json(path, response.value)
        return str(path.relative_to(artifacts.run_directory))

    def write_model_response(
        self,
        artifacts: RunArtifacts,
        *,
        decision_name: str,
        sequence: int,
        response: PersistenceSafeModelArtifact,
    ) -> str:
        if not decision_name or not decision_name.replace("_", "").isalnum():
            raise ValueError("decision_name must contain only letters and underscores")
        if sequence < 1:
            raise ValueError("model response sequence must be positive")
        artifacts.model_responses_directory.mkdir(parents=True, exist_ok=True)
        path = (
            artifacts.model_responses_directory
            / f"{sequence:02d}-{decision_name.replace('_', '-')}.json"
        )
        self._write_json(path, response.value)
        return str(path.relative_to(artifacts.run_directory))

    @staticmethod
    def _write_json(path: Path, value: object) -> None:
        path.write_text(
            json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
