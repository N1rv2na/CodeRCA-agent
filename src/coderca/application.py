"""Application orchestration for a bounded initial Diagnosis Run."""

from __future__ import annotations

import json
from uuid import uuid4

from .context_builder import ContextBuilder, DiagnosisTaskContext
from .contracts import (
    DiagnosisEvent,
    DiagnosisEventFailureCategory,
    DiagnosisFailureCategory,
    DiagnosisReport,
    DiagnosisRunResult,
    DiagnosisStage,
    FormHypothesisDecision,
    RunArtifacts,
    TaskManifest,
)
from .diagnosis_state import DiagnosisStateMachine
from .model_provider import ModelProviderError, StructuredModelProvider
from .run_store import RunStore

_FORMATION_SYSTEM_PROMPT = (
    "Form one falsifiable Root Cause Hypothesis. Return only the "
    "requested structured object; do not include private reasoning."
)
_INFRASTRUCTURE_FAILURES = {"timeout", "network_error", "http_error"}


class DiagnosisApplicationService:
    def __init__(self, provider: StructuredModelProvider, run_store: RunStore) -> None:
        self.provider = provider
        self.run_store = run_store

    def start_diagnosis(self, task: DiagnosisTaskContext) -> DiagnosisRunResult:
        manifest = task.manifest
        run_id = str(uuid4())
        artifacts = self.run_store.create_run(run_id)
        self.run_store.write_manifest(artifacts, manifest)
        state = DiagnosisStateMachine()

        events = [
            DiagnosisEvent(
                sequence=1,
                event_type="run_started",
                run_id=run_id,
                task_id=manifest.task_id,
                stage=DiagnosisStage.PREPARING,
                message="Diagnosis Run accepted and Manifest snapshot persisted.",
            )
        ]
        state.begin_hypothesis_formation()
        events.append(
            DiagnosisEvent(
                sequence=2,
                event_type="stage_changed",
                run_id=run_id,
                task_id=manifest.task_id,
                stage=state.stage,
                message="Diagnosis Run is forming the initial Active Hypothesis.",
            )
        )
        correction: dict[str, object] | None = None
        for attempt in (1, 2):
            try:
                structured_response = self.provider.generate_structured(
                    schema_name="form_hypothesis",
                    system_prompt=_FORMATION_SYSTEM_PROMPT,
                    user_prompt=_build_formation_context(
                        task, state, correction=correction
                    ),
                    response_model=FormHypothesisDecision,
                )
                break
            except ModelProviderError as exc:
                response_artifact = _write_error_response(
                    self.run_store, artifacts, attempt, exc
                )
                validation_errors = _validation_errors(exc)
                structured_failure = _structured_output_failure_category(exc)
                if attempt == 1 and structured_failure is not None:
                    state.authorize_schema_correction()
                    events.append(
                        DiagnosisEvent(
                            sequence=len(events) + 1,
                            event_type="schema_correction_requested",
                            run_id=run_id,
                            task_id=manifest.task_id,
                            stage=state.stage,
                            message=(
                                "Initial Hypothesis output was invalid; one explicit "
                                "schema correction was requested."
                            ),
                            model_response_artifact=response_artifact,
                            failure_category=structured_failure,
                            validation_errors=validation_errors,
                        )
                    )
                    correction = {
                        "attempt": 2,
                        "failure_category": structured_failure,
                        "validation_errors": validation_errors,
                    }
                    continue
                if structured_failure is not None:
                    failure_category: DiagnosisFailureCategory = "schema_failure"
                elif exc.category in _INFRASTRUCTURE_FAILURES:
                    failure_category = "infrastructure_failure"
                else:
                    raise
                return self._finalize_failure(
                    manifest=manifest,
                    run_id=run_id,
                    artifacts=artifacts,
                    state=state,
                    events=events,
                    failure_category=failure_category,
                    model_response_artifact=response_artifact,
                    validation_errors=validation_errors,
                )
        else:  # pragma: no cover - the two-attempt loop always returns or breaks
            raise RuntimeError("Hypothesis formation exhausted without a result")

        response_artifact = self.run_store.write_hypothesis_formation_response(
            artifacts,
            attempt=attempt,
            response=structured_response.persistence_safe_artifact,
        )
        hypothesis = state.form_hypothesis(structured_response.value)
        summary = f"Formed initial Active Hypothesis {hypothesis.hypothesis_id}."
        events.append(
            DiagnosisEvent(
                sequence=len(events) + 1,
                event_type="hypothesis_formed",
                run_id=run_id,
                task_id=manifest.task_id,
                stage=state.stage,
                message=summary,
                hypothesis_history=list(state.hypothesis_history),
                model_response_artifact=response_artifact,
            )
        )
        report = DiagnosisReport(
            run_id=run_id,
            task_id=manifest.task_id,
            stage=DiagnosisStage.DIAGNOSING,
            status="in_progress",
            summary=summary,
            hypothesis_history=list(state.hypothesis_history),
        )
        self.run_store.write_events(artifacts, events)
        self.run_store.write_report(artifacts, report)
        return DiagnosisRunResult(
            run_id=run_id,
            task_id=manifest.task_id,
            stage=DiagnosisStage.DIAGNOSING,
            status="in_progress",
            summary=summary,
            hypothesis_history=state.hypothesis_history,
            run_directory=artifacts.run_directory,
            manifest_path=artifacts.manifest_path,
            events_path=artifacts.events_path,
            report_path=artifacts.report_path,
        )

    def _finalize_failure(
        self,
        *,
        manifest: TaskManifest,
        run_id: str,
        artifacts: RunArtifacts,
        state: DiagnosisStateMachine,
        events: list[DiagnosisEvent],
        failure_category: DiagnosisFailureCategory,
        model_response_artifact: str | None,
        validation_errors: list[dict[str, object]],
    ) -> DiagnosisRunResult:
        state.transition_to(DiagnosisStage.FINALIZING)
        summary = (
            "Initial Hypothesis formation stopped after Schema Failure."
            if failure_category == "schema_failure"
            else "Initial Hypothesis formation stopped after Infrastructure Failure."
        )
        events.append(
            DiagnosisEvent(
                sequence=len(events) + 1,
                event_type="run_failed",
                run_id=run_id,
                task_id=manifest.task_id,
                stage=state.stage,
                message=summary,
                failure_category=failure_category,
                model_response_artifact=model_response_artifact,
                validation_errors=validation_errors,
            )
        )
        report = DiagnosisReport(
            run_id=run_id,
            task_id=manifest.task_id,
            stage=DiagnosisStage.FINALIZING,
            status="failed",
            stop_reason=failure_category,
            summary=summary,
        )
        self.run_store.write_events(artifacts, events)
        self.run_store.write_report(artifacts, report)
        return DiagnosisRunResult(
            run_id=run_id,
            task_id=manifest.task_id,
            stage=DiagnosisStage.FINALIZING,
            status="failed",
            stop_reason=failure_category,
            summary=summary,
            run_directory=artifacts.run_directory,
            manifest_path=artifacts.manifest_path,
            events_path=artifacts.events_path,
            report_path=artifacts.report_path,
        )


def _build_formation_context(
    task: DiagnosisTaskContext,
    state: DiagnosisStateMachine,
    *,
    correction: dict[str, object] | None = None,
) -> str:
    context = ContextBuilder().build_form_hypothesis(task, state)
    if correction is not None:
        context["schema_correction"] = correction
    return json.dumps(context, sort_keys=True)


def _structured_output_failure_category(
    error: ModelProviderError,
) -> DiagnosisEventFailureCategory | None:
    if error.category == "invalid_json":
        return "invalid_json"
    if error.category == "invalid_response":
        return "invalid_response"
    if error.category == "schema_mismatch":
        return "schema_mismatch"
    return None


def _validation_errors(error: ModelProviderError) -> list[dict[str, object]]:
    errors = error.details.get("validation_errors", [])
    if not isinstance(errors, list):
        return []
    return [item for item in errors if isinstance(item, dict)]


def _write_error_response(
    run_store: RunStore,
    artifacts: RunArtifacts,
    attempt: int,
    error: ModelProviderError,
) -> str | None:
    if error.persistence_safe_artifact is None:
        return None
    return run_store.write_hypothesis_formation_response(
        artifacts,
        attempt=attempt,
        response=error.persistence_safe_artifact,
    )
