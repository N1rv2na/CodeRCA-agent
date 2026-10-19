"""Application orchestration for bounded hypothesis-driven Diagnosis Runs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, TypeVar
from uuid import uuid4

from pydantic import BaseModel

from .context_builder import ContextBuilder, DiagnosisTaskContext
from .contracts import (
    DecisionValidationError,
    DiagnosisEvent,
    DiagnosisEventFailureCategory,
    DiagnosisFailureCategory,
    DiagnosisReport,
    DiagnosisRunResult,
    DiagnosisStage,
    DiagnosisStopReason,
    Experiment,
    FormHypothesisDecision,
    HypothesisAssessmentDecision,
    PatchDecision,
    PatchValidationAction,
    PublicValidationResult,
    ReformulateHypothesisDecision,
    ReportDecision,
    RunArtifacts,
    SelectExperimentDecision,
    TaskManifest,
    UpdateEvidenceDecision,
)
from .diagnosis_state import DiagnosisStateMachine, InvalidDiagnosisTransition
from .model_provider import (
    ModelProviderError,
    StructuredModelProvider,
    StructuredModelResponse,
)
from .run_store import RunStore
from .tool_runtime import ToolRuntime

_FORMATION_SYSTEM_PROMPT = (
    "Form one falsifiable Root Cause Hypothesis. Return only the "
    "requested structured object; do not include private reasoning."
)
_INFRASTRUCTURE_FAILURES = {"timeout", "network_error", "http_error"}

DecisionModel = TypeVar("DecisionModel", bound=BaseModel)


@dataclass(frozen=True)
class _LoopDecisionFailure(RuntimeError):
    failure_category: DiagnosisFailureCategory
    model_response_artifact: str | None
    validation_errors: list[dict[str, object]]


class DiagnosisApplicationService:
    def __init__(
        self,
        provider: StructuredModelProvider,
        run_store: RunStore,
        tool_runtime: ToolRuntime | None = None,
    ) -> None:
        self.provider = provider
        self.run_store = run_store
        self.tool_runtime = tool_runtime

    def start_diagnosis(self, task: DiagnosisTaskContext) -> DiagnosisRunResult:
        manifest = task.manifest
        run_id = str(uuid4())
        artifacts = self.run_store.create_run(run_id)
        self.run_store.write_manifest(artifacts, manifest)
        state = DiagnosisStateMachine(tool_call_limit=manifest.tool_call_limit)

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
        hypothesis = state.form_initial_hypothesis(structured_response.value)
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
        if self.tool_runtime is not None:
            return self._run_diagnosis_loop(
                task=task,
                run_id=run_id,
                artifacts=artifacts,
                state=state,
                events=events,
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

    def _run_diagnosis_loop(
        self,
        *,
        task: DiagnosisTaskContext,
        run_id: str,
        artifacts: RunArtifacts,
        state: DiagnosisStateMachine,
        events: list[DiagnosisEvent],
    ) -> DiagnosisRunResult:
        try:
            return self._run_diagnosis_loop_unchecked(
                task=task,
                run_id=run_id,
                artifacts=artifacts,
                state=state,
                events=events,
            )
        except _LoopDecisionFailure as failure:
            return self._finalize_failure(
                manifest=task.manifest,
                run_id=run_id,
                artifacts=artifacts,
                state=state,
                events=events,
                failure_category=failure.failure_category,
                model_response_artifact=failure.model_response_artifact,
                validation_errors=failure.validation_errors,
            )
        except InvalidDiagnosisTransition as exc:
            return self._finalize_failure(
                manifest=task.manifest,
                run_id=run_id,
                artifacts=artifacts,
                state=state,
                events=events,
                failure_category="schema_failure",
                model_response_artifact=None,
                validation_errors=[
                    {"type": "state_invariant", "message": str(exc)}
                ],
            )

    def _run_diagnosis_loop_unchecked(
        self,
        *,
        task: DiagnosisTaskContext,
        run_id: str,
        artifacts: RunArtifacts,
        state: DiagnosisStateMachine,
        events: list[DiagnosisEvent],
    ) -> DiagnosisRunResult:
        model_sequence = 1
        runtime = self.tool_runtime
        if runtime is None:  # guarded by start_diagnosis
            raise RuntimeError("diagnosis requires a Tool Runtime")
        while True:
            if state.tool_budget_exhausted:
                return self._finalize_diagnosis(
                    task=task,
                    run_id=run_id,
                    artifacts=artifacts,
                    state=state,
                    events=events,
                    stop_reason="tool_budget_exhausted",
                    summary="Diagnosis stopped after exhausting Tool Budget.",
                )
            select_context = ContextBuilder().build_select_experiment(
                task,
                state,
                available_tools=runtime.available_tool_catalog(),
                experiments=list(state.experiments),
                observations=list(state.observations),
                evidence=list(state.evidence),
                used_tool_calls=state.used_tool_calls,
            )
            selected, selected_artifact, model_sequence = self._request_loop_decision(
                task=task,
                run_id=run_id,
                state=state,
                events=events,
                artifacts=artifacts,
                schema_name="select_experiment",
                system_prompt=(
                    "Select one falsification-first read-only Experiment using "
                    "exactly one tool from available_tools and arguments matching "
                    "that tool's input_schema. Return only the requested structured "
                    "object."
                ),
                context=select_context,
                response_model=SelectExperimentDecision,
                model_sequence=model_sequence,
                decision_validator=lambda value: runtime.validate_selection(
                    value.tool_name, value.arguments
                ),
            )
            decision = selected.value
            experiment = Experiment(
                experiment_id=f"X{state.used_tool_calls + 1}",
                hypothesis_id=decision.hypothesis_id,
                purpose=decision.purpose,
                expected_observation=decision.expected_observation,
                falsification_relevance=decision.falsification_relevance,
                tool_name=decision.tool_name,
                arguments=decision.arguments,
            )
            state.begin_experiment(experiment)
            tool_result = runtime.execute(
                experiment,
                artifact_directory=artifacts.run_directory / "tool-results",
            )
            events.append(
                DiagnosisEvent(
                    sequence=len(events) + 1,
                    event_type="tool_executed",
                    run_id=run_id,
                    task_id=task.manifest.task_id,
                    stage=state.stage,
                    message=(
                        f"Executed {experiment.tool_name} for "
                        f"{experiment.hypothesis_id}."
                    ),
                    hypothesis_history=list(state.hypothesis_history),
                    model_response_artifact=selected_artifact,
                    experiment=experiment,
                    tool_result=tool_result,
                )
            )
            if tool_result.status == "error":
                return self._finalize_diagnosis(
                    task=task,
                    run_id=run_id,
                    artifacts=artifacts,
                    state=state,
                    events=events,
                    stop_reason="tool_failure",
                    summary=(
                        "Diagnosis stopped after "
                        f"{tool_result.error_category}."
                    ),
                    failed=True,
                )
            observation = state.record_observation(tool_result)
            evidence_context = ContextBuilder().build_update_evidence(
                task,
                state,
                experiment=experiment,
                latest_observation=observation,
                evidence=list(state.evidence),
            )
            updated, evidence_artifact, model_sequence = self._request_loop_decision(
                task=task,
                run_id=run_id,
                state=state,
                events=events,
                artifacts=artifacts,
                schema_name="update_evidence",
                system_prompt=(
                    "Interpret the real Observation as qualitative Evidence. Return "
                    "only the requested structured object."
                ),
                context=evidence_context,
                response_model=UpdateEvidenceDecision,
                model_sequence=model_sequence,
            )
            evidence = state.record_evidence(updated.value)
            events.append(
                DiagnosisEvent(
                    sequence=len(events) + 1,
                    event_type="evidence_recorded",
                    run_id=run_id,
                    task_id=task.manifest.task_id,
                    stage=state.stage,
                    message=(
                        f"Recorded {evidence.evidence_id} for {evidence.hypothesis_id}."
                    ),
                    hypothesis_history=list(state.hypothesis_history),
                    model_response_artifact=evidence_artifact,
                    observation=observation,
                    evidence=evidence,
                )
            )
            assessment_context = ContextBuilder().build_assess_hypothesis(
                task,
                state,
                observations=list(state.observations),
                evidence=list(state.evidence),
                used_tool_calls=state.used_tool_calls,
            )
            assessed, assessment_artifact, model_sequence = self._request_loop_decision(
                task=task,
                run_id=run_id,
                state=state,
                events=events,
                artifacts=artifacts,
                schema_name="assess_hypothesis",
                system_prompt=(
                    "Assess the Active Hypothesis from registered Evidence. "
                    "evidence_refs may contain only evidence_id values listed in "
                    "relevant_evidence; never cite Observation, Experiment, or Tool "
                    "Result IDs. Return only the requested structured object."
                ),
                context=assessment_context,
                response_model=HypothesisAssessmentDecision,
                model_sequence=model_sequence,
                decision_validator=state.validate_hypothesis_assessment,
            )
            assessed_hypothesis = state.apply_hypothesis_assessment(assessed.value)
            events.append(
                DiagnosisEvent(
                    sequence=len(events) + 1,
                    event_type="hypothesis_assessed",
                    run_id=run_id,
                    task_id=task.manifest.task_id,
                    stage=state.stage,
                    message=(
                        f"Assessed {assessed_hypothesis.hypothesis_id} as "
                        f"{assessed_hypothesis.status}."
                    ),
                    hypothesis_history=list(state.hypothesis_history),
                    model_response_artifact=assessment_artifact,
                )
            )
            if assessed_hypothesis.status == "supported":
                if runtime.registered_test_command is not None:
                    if state.tool_budget_exhausted:
                        return self._finalize_diagnosis(
                            task=task,
                            run_id=run_id,
                            artifacts=artifacts,
                            state=state,
                            events=events,
                            stop_reason="tool_budget_exhausted",
                            summary=(
                                "Diagnosis supported a Hypothesis but exhausted "
                                "Tool Budget before Patch Validation."
                            ),
                        )
                    return self._run_patch_validation(
                        task=task,
                        run_id=run_id,
                        artifacts=artifacts,
                        state=state,
                        events=events,
                        runtime=runtime,
                        model_sequence=model_sequence,
                    )
                return self._finalize_diagnosis(
                    task=task,
                    run_id=run_id,
                    artifacts=artifacts,
                    state=state,
                    events=events,
                    stop_reason="read_only_diagnosis_complete",
                    summary=(
                        f"Read-only diagnosis supported "
                        f"{assessed_hypothesis.hypothesis_id}."
                    ),
                )
            if assessed_hypothesis.status in {"rejected", "inconclusive"}:
                if state.hypothesis_budget_exhausted:
                    return self._finalize_diagnosis(
                        task=task,
                        run_id=run_id,
                        artifacts=artifacts,
                        state=state,
                        events=events,
                        stop_reason="hypothesis_budget_exhausted",
                        summary="Diagnosis exhausted H1-H3.",
                    )
                state.begin_hypothesis_formation()
                reformulation_context = ContextBuilder().build_form_hypothesis(
                    task,
                    state,
                    observations=list(state.observations),
                    evidence=list(state.evidence),
                )
                (
                    reformulated,
                    reformulation_artifact,
                    model_sequence,
                ) = self._request_loop_decision(
                    task=task,
                    run_id=run_id,
                    state=state,
                    events=events,
                    artifacts=artifacts,
                    schema_name="reformulate_hypothesis",
                    system_prompt=(
                        "Reformulate one materially different Hypothesis from "
                        "registered Evidence IDs. Return only the requested object."
                    ),
                    context=reformulation_context,
                    response_model=ReformulateHypothesisDecision,
                    model_sequence=model_sequence,
                )
                new_hypothesis = state.reformulate_hypothesis(reformulated.value)
                events.append(
                    DiagnosisEvent(
                        sequence=len(events) + 1,
                        event_type="hypothesis_reformulated",
                        run_id=run_id,
                        task_id=task.manifest.task_id,
                        stage=state.stage,
                        message=(
                            f"Formed Active Hypothesis {new_hypothesis.hypothesis_id}."
                        ),
                        hypothesis_history=list(state.hypothesis_history),
                        model_response_artifact=reformulation_artifact,
                    )
                )

    def _run_patch_validation(
        self,
        *,
        task: DiagnosisTaskContext,
        run_id: str,
        artifacts: RunArtifacts,
        state: DiagnosisStateMachine,
        events: list[DiagnosisEvent],
        runtime: ToolRuntime,
        model_sequence: int,
    ) -> DiagnosisRunResult:
        supported = state.supported_hypothesis
        if supported is None:
            raise InvalidDiagnosisTransition(
                "Patch generation requires one supported Hypothesis"
            )
        validation_context = ContextBuilder().build_validation(
            task,
            state,
            observations=list(state.observations),
            evidence=list(state.evidence),
        )

        def validate_binding(value: PatchDecision) -> None:
            if value.hypothesis_id != supported.hypothesis_id:
                raise DecisionValidationError(
                    "Patch must bind the supported Hypothesis",
                    [
                        {
                            "loc": ["hypothesis_id"],
                            "type": "wrong_hypothesis",
                            "msg": "Patch does not bind the supported Hypothesis.",
                            "input": value.hypothesis_id,
                            "allowed_hypothesis_id": supported.hypothesis_id,
                        }
                    ],
                )

        generated, patch_artifact, model_sequence = self._request_loop_decision(
            task=task,
            run_id=run_id,
            state=state,
            events=events,
            artifacts=artifacts,
            schema_name="generate_patch",
            system_prompt=(
                "Generate exactly one unified diff for the supported Hypothesis. "
                "Modify only one permitted business source file and return only "
                "the requested structured object."
            ),
            context=validation_context,
            response_model=PatchDecision,
            model_sequence=model_sequence,
            decision_validator=validate_binding,
        )
        patch = generated.value
        validation_action = PatchValidationAction(
            validation_action_id="V1",
            hypothesis_id=patch.hypothesis_id,
            purpose="Apply the candidate patch and run Public Validation.",
            tool_name="apply_patch",
            arguments={
                "target_path": patch.target_path,
                "unified_diff": patch.unified_diff,
            },
        )
        state.begin_validation(validation_action)
        events.append(
            DiagnosisEvent(
                sequence=len(events) + 1,
                event_type="patch_generated",
                run_id=run_id,
                task_id=task.manifest.task_id,
                stage=state.stage,
                message=(
                    f"Generated one candidate patch for {patch.hypothesis_id}."
                ),
                hypothesis_history=list(state.hypothesis_history),
                model_response_artifact=patch_artifact,
                patch=patch,
                validation_action=validation_action,
            )
        )
        patch_tool_result, validation = runtime.execute_patch_validation(
            validation_action,
            patch,
            artifact_directory=artifacts.run_directory,
        )
        validation_observation, validation_evidence = state.record_public_validation(
            validation,
            validation_action,
            patch_tool_result,
        )
        events.append(
            DiagnosisEvent(
                sequence=len(events) + 1,
                event_type="validation_completed",
                run_id=run_id,
                task_id=task.manifest.task_id,
                stage=state.stage,
                message=f"Public Validation {validation.status}.",
                hypothesis_history=list(state.hypothesis_history),
                patch=patch,
                validation=validation,
                observation=validation_observation,
                evidence=validation_evidence,
                validation_action=validation_action,
                tool_result=patch_tool_result,
            )
        )
        report_context = ContextBuilder().build_validation(
            task,
            state,
            observations=list(state.observations),
            evidence=list(state.evidence),
        )
        report_context["candidate_patch"] = patch.model_dump(mode="json")
        report_context["public_validation"] = validation.model_dump(mode="json")
        generated_report, report_artifact, _ = self._request_loop_decision(
            task=task,
            run_id=run_id,
            state=state,
            events=events,
            artifacts=artifacts,
            schema_name="generate_report",
            system_prompt=(
                "Complete the causal fields for the final Root Cause Report from "
                "the supported Hypothesis, registered Evidence, candidate patch, "
                "and Public Validation. Return only the requested object."
            ),
            context=report_context,
            response_model=ReportDecision,
            model_sequence=model_sequence,
        )
        root_cause_analysis = generated_report.value
        events.append(
            DiagnosisEvent(
                sequence=len(events) + 1,
                event_type="report_generated",
                run_id=run_id,
                task_id=task.manifest.task_id,
                stage=state.stage,
                message="Generated the final Root Cause Report causal fields.",
                hypothesis_history=list(state.hypothesis_history),
                model_response_artifact=report_artifact,
                patch=patch,
                validation=validation,
                root_cause_analysis=root_cause_analysis,
            )
        )
        return self._finalize_validation(
            task=task,
            run_id=run_id,
            artifacts=artifacts,
            state=state,
            events=events,
            patch=patch,
            validation=validation,
            root_cause_analysis=root_cause_analysis,
        )

    def _finalize_validation(
        self,
        *,
        task: DiagnosisTaskContext,
        run_id: str,
        artifacts: RunArtifacts,
        state: DiagnosisStateMachine,
        events: list[DiagnosisEvent],
        patch: PatchDecision,
        validation: PublicValidationResult,
        root_cause_analysis: ReportDecision,
    ) -> DiagnosisRunResult:
        state.transition_to(DiagnosisStage.FINALIZING)
        stop_reason: DiagnosisStopReason = (
            "validation_passed"
            if validation.status == "passed"
            else "validation_failed"
        )
        summary = f"Public Validation {validation.status} for {patch.hypothesis_id}."
        events.append(
            DiagnosisEvent(
                sequence=len(events) + 1,
                event_type="run_completed",
                run_id=run_id,
                task_id=task.manifest.task_id,
                stage=state.stage,
                message=summary,
                hypothesis_history=list(state.hypothesis_history),
                patch=patch,
                validation=validation,
                root_cause_analysis=root_cause_analysis,
            )
        )
        report = DiagnosisReport(
            run_id=run_id,
            task_id=task.manifest.task_id,
            stage=state.stage,
            status="completed",
            stop_reason=stop_reason,
            summary=summary,
            hypothesis_history=list(state.hypothesis_history),
            final_hypothesis=state.supported_hypothesis,
            observations=list(state.observations),
            evidence=list(state.evidence),
            patch=patch,
            validation=validation,
            root_cause_analysis=root_cause_analysis,
        )
        self.run_store.write_events(artifacts, events)
        self.run_store.write_report(artifacts, report)
        return DiagnosisRunResult(
            run_id=run_id,
            task_id=task.manifest.task_id,
            stage=state.stage,
            status="completed",
            stop_reason=stop_reason,
            summary=summary,
            hypothesis_history=state.hypothesis_history,
            observations=state.observations,
            evidence=state.evidence,
            patch=patch,
            validation=validation,
            root_cause_analysis=root_cause_analysis,
            run_directory=artifacts.run_directory,
            manifest_path=artifacts.manifest_path,
            events_path=artifacts.events_path,
            report_path=artifacts.report_path,
        )

    def _request_loop_decision(
        self,
        *,
        task: DiagnosisTaskContext,
        run_id: str,
        state: DiagnosisStateMachine,
        events: list[DiagnosisEvent],
        artifacts: RunArtifacts,
        schema_name: str,
        system_prompt: str,
        context: dict[str, object],
        response_model: type[DecisionModel],
        model_sequence: int,
        decision_validator: Callable[[DecisionModel], object] | None = None,
    ) -> tuple[StructuredModelResponse[DecisionModel], str, int]:
        correction: dict[str, object] | None = None
        last_artifact: str | None = None
        last_errors: list[dict[str, object]] = []
        for attempt in (1, 2):
            request_context = dict(context)
            if correction is not None:
                request_context["schema_correction"] = correction
            try:
                response = self.provider.generate_structured(
                    schema_name=schema_name,
                    system_prompt=system_prompt,
                    user_prompt=json.dumps(request_context, sort_keys=True),
                    response_model=response_model,
                )
                if decision_validator is not None:
                    try:
                        decision_validator(response.value)
                    except DecisionValidationError as exc:
                        raise ModelProviderError(
                            "schema_mismatch",
                            str(exc),
                            {"validation_errors": exc.validation_errors},
                            persistence_safe_artifact=(
                                response.persistence_safe_artifact
                            ),
                        ) from exc
            except ModelProviderError as exc:
                model_sequence += 1
                last_errors = _validation_errors(exc)
                if exc.persistence_safe_artifact is not None:
                    last_artifact = self.run_store.write_model_response(
                        artifacts,
                        decision_name=f"{schema_name}_invalid",
                        sequence=model_sequence,
                        response=exc.persistence_safe_artifact,
                    )
                structured_failure = _structured_output_failure_category(exc)
                if attempt == 1 and structured_failure is not None:
                    events.append(
                        DiagnosisEvent(
                            sequence=len(events) + 1,
                            event_type="schema_correction_requested",
                            run_id=run_id,
                            task_id=task.manifest.task_id,
                            stage=state.stage,
                            message=(
                                f"{schema_name} output was invalid; one explicit "
                                "schema correction was requested."
                            ),
                            hypothesis_history=list(state.hypothesis_history),
                            model_response_artifact=last_artifact,
                            failure_category=structured_failure,
                            validation_errors=last_errors,
                        )
                    )
                    correction = {
                        "attempt": 2,
                        "failure_category": structured_failure,
                        "validation_errors": last_errors,
                    }
                    continue
                if structured_failure is not None:
                    category: DiagnosisFailureCategory = "schema_failure"
                elif exc.category in _INFRASTRUCTURE_FAILURES:
                    category = "infrastructure_failure"
                else:
                    raise
                raise _LoopDecisionFailure(
                    category, last_artifact, last_errors
                ) from exc
            model_sequence += 1
            artifact = self.run_store.write_model_response(
                artifacts,
                decision_name=schema_name,
                sequence=model_sequence,
                response=response.persistence_safe_artifact,
            )
            return response, artifact, model_sequence
        raise RuntimeError("structured decision correction loop exhausted")

    def _finalize_diagnosis(
        self,
        *,
        task: DiagnosisTaskContext,
        run_id: str,
        artifacts: RunArtifacts,
        state: DiagnosisStateMachine,
        events: list[DiagnosisEvent],
        stop_reason: DiagnosisStopReason,
        summary: str,
        failed: bool = False,
    ) -> DiagnosisRunResult:
        state.transition_to(DiagnosisStage.FINALIZING)
        final_hypothesis = (
            state.hypothesis_history[-1] if state.hypothesis_history else None
        )
        events.append(
            DiagnosisEvent(
                sequence=len(events) + 1,
                event_type="run_failed" if failed else "run_completed",
                run_id=run_id,
                task_id=task.manifest.task_id,
                stage=state.stage,
                message=summary,
                hypothesis_history=list(state.hypothesis_history),
                failure_category=None,
            )
        )
        report = DiagnosisReport(
            run_id=run_id,
            task_id=task.manifest.task_id,
            stage=state.stage,
            status="failed" if failed else "completed",
            stop_reason=stop_reason,
            summary=summary,
            hypothesis_history=list(state.hypothesis_history),
            final_hypothesis=final_hypothesis,
            observations=list(state.observations),
            evidence=list(state.evidence),
        )
        self.run_store.write_events(artifacts, events)
        self.run_store.write_report(artifacts, report)
        return DiagnosisRunResult(
            run_id=run_id,
            task_id=task.manifest.task_id,
            stage=state.stage,
            status="failed" if failed else "completed",
            stop_reason=stop_reason,
            summary=summary,
            hypothesis_history=state.hypothesis_history,
            observations=state.observations,
            evidence=state.evidence,
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
            "Diagnosis Run stopped after Schema Failure."
            if failure_category == "schema_failure"
            else "Diagnosis Run stopped after Infrastructure Failure."
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
                hypothesis_history=list(state.hypothesis_history),
            )
        )
        final_hypothesis = (
            state.hypothesis_history[-1] if state.hypothesis_history else None
        )
        report = DiagnosisReport(
            run_id=run_id,
            task_id=manifest.task_id,
            stage=DiagnosisStage.FINALIZING,
            status="failed",
            stop_reason=failure_category,
            summary=summary,
            hypothesis_history=list(state.hypothesis_history),
            final_hypothesis=final_hypothesis,
            observations=list(state.observations),
            evidence=list(state.evidence),
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
            hypothesis_history=state.hypothesis_history,
            observations=state.observations,
            evidence=state.evidence,
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
