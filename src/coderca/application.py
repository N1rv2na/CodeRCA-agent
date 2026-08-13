"""Diagnosis Application Service for the CRCA-001 walking skeleton."""

from __future__ import annotations

from uuid import uuid4

from .contracts import (
    DiagnosisEvent,
    DiagnosisReport,
    DiagnosisRunResult,
    ModelCompletion,
    TaskManifest,
)
from .model_provider import ModelProvider
from .run_store import RunStore


class DiagnosisApplicationService:
    def __init__(self, provider: ModelProvider, run_store: RunStore) -> None:
        self.provider = provider
        self.run_store = run_store

    def start_diagnosis(self, manifest: TaskManifest) -> DiagnosisRunResult:
        self.provider.ensure_ready()
        run_id = str(uuid4())
        artifacts = self.run_store.create_run(run_id)
        self.run_store.write_manifest(artifacts, manifest)

        events = [
            DiagnosisEvent(
                sequence=1,
                event_type="run_started",
                run_id=run_id,
                task_id=manifest.task_id,
                stage="preparing",
                message="Diagnosis Run accepted and Manifest snapshot persisted.",
            )
        ]
        completion: ModelCompletion = self.provider.complete(manifest)
        events.append(
            DiagnosisEvent(
                sequence=2,
                event_type="run_completed",
                run_id=run_id,
                task_id=manifest.task_id,
                stage=completion.stage,
                message=completion.summary,
            )
        )
        report = DiagnosisReport(
            run_id=run_id,
            task_id=manifest.task_id,
            stage=completion.stage,
            status=completion.status,
            stop_reason=completion.stop_reason,
            summary=completion.summary,
        )
        self.run_store.write_events(artifacts, events)
        self.run_store.write_report(artifacts, report)
        return DiagnosisRunResult(
            run_id=run_id,
            task_id=manifest.task_id,
            stage=completion.stage,
            status=completion.status,
            stop_reason=completion.stop_reason,
            summary=completion.summary,
            run_directory=artifacts.run_directory,
            manifest_path=artifacts.manifest_path,
            events_path=artifacts.events_path,
            report_path=artifacts.report_path,
        )
