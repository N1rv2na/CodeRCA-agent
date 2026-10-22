"""Deterministic per-task Engineering Evaluation over persisted Run Artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from pydantic import model_validator

from .context_builder import DiagnosisTaskContext
from .contracts import (
    ContractModel,
    DiagnosisEvent,
    DiagnosisRunResult,
    EvaluationGroundTruth,
    FinalRootCauseLocation,
    HypothesisAssessmentDecision,
    PatchIntentDecision,
    PublicValidationResult,
    TaskManifest,
)
from .localization import (
    artifact_path,
    audit_evidence,
    normalize_legacy_report,
    read_persisted_report,
    validate_location_sources,
)
from .patch_compiler import PatchIntentCompilationError, verify_compiled_candidate

CheckStatus = Literal["passed", "failed", "not_run"]
LocationStatus = Literal["hit", "miss", "not_provided"]
ApplicabilityStatus = Literal["applicable", "invalid", "not_run"]
SearchCapability = Literal["verified", "not_demonstrated", "invalid_trajectory"]
CausalFieldStatus = Literal["pending", "match", "mismatch"]

_ACTIVE = {"proposed", "testing"}
_TERMINAL = {"supported", "rejected", "inconclusive"}


class OutcomeEvaluation(ContractModel):
    location: LocationStatus
    root_location: FinalRootCauseLocation | None = None
    patch_intent_compilation: CheckStatus
    candidate_patch: ApplicabilityStatus
    validation: CheckStatus
    report_contract: CheckStatus
    passed: bool
    violations: tuple[str, ...] = ()


class TrajectoryEvaluation(ContractModel):
    passed: bool
    violations: tuple[str, ...] = ()


class CausalReviewRecord(ContractModel):
    """Human comparison of observable causal fields with frozen Ground Truth."""

    task_id: str
    reviewer: str | None = None
    trigger_condition: CausalFieldStatus = "pending"
    defect_location: CausalFieldStatus = "pending"
    propagation_path: CausalFieldStatus = "pending"
    failure_manifestation: CausalFieldStatus = "pending"
    notes: str = ""
    status: Literal["pending", "passed", "failed"] = "pending"

    @model_validator(mode="before")
    @classmethod
    def derive_status(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        fields = (
            data.get("trigger_condition", "pending"),
            data.get("defect_location", "pending"),
            data.get("propagation_path", "pending"),
            data.get("failure_manifestation", "pending"),
        )
        data["status"] = (
            "failed"
            if "mismatch" in fields
            else "passed"
            if all(item == "match" for item in fields)
            else "pending"
        )
        return data

    @model_validator(mode="after")
    def require_reviewer_for_completed_review(self) -> CausalReviewRecord:
        if self.status != "pending" and not self.reviewer:
            raise ValueError("completed causal review requires a reviewer")
        return self

    @classmethod
    def pending(cls, task_id: str) -> CausalReviewRecord:
        return cls(task_id=task_id)


class TaskEvaluationResult(ContractModel):
    task_id: str
    run_id: str
    run_directory: str
    outcome: OutcomeEvaluation
    trajectory: TrajectoryEvaluation
    search_capability: SearchCapability
    causal_review: CausalReviewRecord
    accepted: bool


class EvaluationSuiteResult(ContractModel):
    schema_version: Literal["1"] = "1"
    tasks: tuple[TaskEvaluationResult, ...]


class EvaluationRunService(Protocol):
    def start_diagnosis(self, task: DiagnosisTaskContext) -> DiagnosisRunResult:
        """Run one task through the canonical Diagnosis Application Service."""


@dataclass(frozen=True)
class EvaluationCase:
    task: DiagnosisTaskContext
    ground_truth: EvaluationGroundTruth
    causal_review: CausalReviewRecord | None = None


class EvaluationHarness:
    """Thin adapter around the canonical Diagnosis Application Service."""

    def run_case(
        self,
        service: EvaluationRunService,
        case: EvaluationCase,
    ) -> TaskEvaluationResult:
        result = service.start_diagnosis(case.task)
        return evaluate_run(
            result.run_directory,
            case.ground_truth,
            causal_review=case.causal_review,
        )


_TASK_ORDER = (
    "crca-002-task-1",
    "crca-010-task-2",
    "crca-011-task-3",
)
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_ground_truth(task_id: str) -> EvaluationGroundTruth:
    """Load author-only truth for one frozen task without exposing it to the Agent."""

    try:
        index = _TASK_ORDER.index(task_id) + 1
    except ValueError as exc:
        raise ValueError(f"unknown frozen Evaluation task: {task_id}") from exc
    path = (
        _PROJECT_ROOT
        / "benchmarks"
        / "django-waffle"
        / f"task-{index}"
        / "ground_truth.json"
    )
    truth = EvaluationGroundTruth.model_validate_json(path.read_text())
    if truth.task_id != task_id:
        raise ValueError("Ground Truth task ID differs from requested task")
    return truth


def load_frozen_manifest(task_id: str) -> TaskManifest:
    """Load the canonical Manifest paired with one frozen Evaluation task."""

    try:
        index = _TASK_ORDER.index(task_id) + 1
    except ValueError as exc:
        raise ValueError(f"unknown frozen Evaluation task: {task_id}") from exc
    path = (
        _PROJECT_ROOT
        / "benchmarks"
        / "django-waffle"
        / f"task-{index}"
        / "manifest.json"
    )
    manifest = TaskManifest.model_validate_json(path.read_text())
    if manifest.task_id != task_id:
        raise ValueError("frozen Manifest task ID differs from requested task")
    return manifest


def evaluate_suite(
    run_directories: tuple[Path, ...],
    *,
    causal_reviews: dict[str, CausalReviewRecord] | None = None,
) -> EvaluationSuiteResult:
    """Evaluate persisted runs in frozen task order without aggregate metrics."""

    reviews = causal_reviews or {}
    results: dict[str, TaskEvaluationResult] = {}
    for directory in run_directories:
        manifest = TaskManifest.model_validate_json(
            artifact_path(directory, "manifest.json").read_text()
        )
        if manifest.task_id in results:
            raise ValueError(f"duplicate Evaluation task: {manifest.task_id}")
        results[manifest.task_id] = evaluate_run(
            directory,
            load_ground_truth(manifest.task_id),
            causal_review=reviews.get(manifest.task_id),
        )
    ordered = tuple(results[task_id] for task_id in _TASK_ORDER if task_id in results)
    unmatched_reviews = set(reviews).difference(results)
    if unmatched_reviews:
        names = ", ".join(sorted(unmatched_reviews))
        raise ValueError(f"Causal Review has no corresponding run: {names}")
    return EvaluationSuiteResult(tasks=ordered)


def _read_events(directory: Path) -> tuple[list[DiagnosisEvent], tuple[str, ...]]:
    events: list[DiagnosisEvent] = []
    violations: list[str] = []
    for line in artifact_path(directory, "events.jsonl").read_text().splitlines():
        if not line.strip():
            continue
        try:
            raw = normalize_legacy_report(json.loads(line))
            if not isinstance(raw, dict):
                raise ValueError("event must be a JSON object")
            experiment = raw.get("experiment")
            if raw.get("event_type") == "tool_executed" and isinstance(
                experiment, dict
            ):
                required = (
                    "purpose",
                    "expected_observation",
                    "falsification_relevance",
                )
                if any(not experiment.get(field) for field in required):
                    violations.append("experiment_metadata_missing")
            events.append(DiagnosisEvent.model_validate(raw))
        except (json.JSONDecodeError, TypeError, ValueError):
            violations.append("invalid_event_contract")
    return events, tuple(dict.fromkeys(violations))


def _read_json_artifact(directory: Path, ref: str) -> object:
    value = json.loads(artifact_path(directory, ref).read_text())
    if isinstance(value, dict) and "choices" in value:
        return json.loads(value["choices"][0]["message"]["content"])
    return value


def _outcome(
    directory: Path,
    manifest: TaskManifest,
    truth: EvaluationGroundTruth,
    report: object,
    events: list[DiagnosisEvent],
) -> OutcomeEvaluation:
    from .contracts import DiagnosisReport

    assert isinstance(report, DiagnosisReport)
    violations: list[str] = []
    analysis = report.root_cause_analysis
    location_status: LocationStatus = "not_provided"
    if analysis is not None and analysis.location is not None:
        location = analysis.location
        try:
            final = report.final_hypothesis
            if final is None or final.status != "supported":
                raise ValueError("final location requires a supported Hypothesis")
            validate_location_sources(
                location,
                final.hypothesis_id,
                manifest,
                report.evidence,
                report.observations,
                events,
                directory,
                evidence_basis=final.evidence_basis,
            )
            hit = (
                location.path == truth.root_path
                and location.symbol in truth.accepted_root_symbols
                and location.start_line <= truth.root_start_line
                and location.end_line >= truth.root_end_line
            )
            location_status = "hit" if hit else "miss"
            if not hit:
                violations.append("root_location_miss")
        except ValueError:
            location_status = "miss"
            violations.append("invalid_root_location_provenance")
    else:
        violations.append("root_location_not_provided")

    report_status: CheckStatus = "passed" if analysis is not None else "failed"
    if report_status == "failed":
        violations.append("root_cause_report_missing")

    patch_events = [event for event in events if event.event_type == "patch_generated"]
    patch_intent_status: CheckStatus = "not_run"
    patch_status: ApplicabilityStatus = "not_run"
    if patch_events:
        event = patch_events[0]
        try:
            if len(patch_events) != 1 or event.patch is None:
                raise ValueError("invalid Patch event count or payload")
            if not event.model_response_artifact:
                raise ValueError("Patch event lacks Patch Intent artifact")
            intent = PatchIntentDecision.model_validate(
                _read_json_artifact(directory, event.model_response_artifact)
            )
            verify_compiled_candidate(intent, event.patch)
            if report.patch != event.patch:
                raise ValueError("Patch event differs from final report")
            patch_intent_status = "passed"
        except (
            OSError,
            ValueError,
            KeyError,
            IndexError,
            TypeError,
            PatchIntentCompilationError,
        ):
            patch_intent_status = "failed"
            violations.append("patch_intent_compilation_failed")
    elif report.final_hypothesis and report.final_hypothesis.status == "supported":
        patch_intent_status = "failed"
        violations.append("supported_hypothesis_without_patch_intent")

    validation_status: CheckStatus = "not_run"
    if report.patch is not None:
        try:
            validation = report.validation
            if validation is None:
                raise ValueError("Candidate Patch lacks Validation")
            patch_text = artifact_path(
                directory, validation.patch_artifact_ref
            ).read_text()
            if patch_text != report.patch.unified_diff.rstrip("\n") + "\n":
                raise ValueError("Candidate Patch artifact mismatch")
            if (
                validation.static_check is None
                and validation.registered_test is None
            ):
                raise ValueError("Validation did not reach a post-apply check")
            patch_status = "applicable"
        except (OSError, ValueError):
            patch_status = "invalid"
            violations.append("candidate_patch_invalid")
    if report.validation is not None:
        try:
            validation = report.validation
            persisted = PublicValidationResult.model_validate_json(
                artifact_path(directory, validation.artifact_ref).read_text()
            )
            if persisted != validation or not any(
                event.validation == validation for event in events
            ):
                raise ValueError("Validation differs from recorded artifacts")
            for check in (validation.static_check, validation.registered_test):
                if check is not None:
                    artifact_path(directory, check.artifact_ref)
            validation_status = validation.status
            if validation.status != "passed":
                violations.append("public_validation_failed")
        except (OSError, ValueError):
            validation_status = "failed"
            violations.append("invalid_public_validation_artifact")

    passed = (
        report.status == "completed"
        and location_status == "hit"
        and patch_intent_status == "passed"
        and patch_status == "applicable"
        and validation_status == "passed"
        and report_status == "passed"
    )
    return OutcomeEvaluation(
        location=location_status,
        root_location=analysis.location if analysis is not None else None,
        patch_intent_compilation=patch_intent_status,
        candidate_patch=patch_status,
        validation=validation_status,
        report_contract=report_status,
        passed=passed,
        violations=tuple(dict.fromkeys(violations)),
    )


def _trajectory(
    directory: Path,
    manifest: TaskManifest,
    report: object,
    events: list[DiagnosisEvent],
    event_contract_violations: tuple[str, ...] = (),
) -> TrajectoryEvaluation:
    from .contracts import DiagnosisReport

    assert isinstance(report, DiagnosisReport)
    violations = list(event_contract_violations)
    if [event.sequence for event in events] != list(range(1, len(events) + 1)):
        violations.append("invalid_event_sequence")
    if any(
        event.run_id != report.run_id or event.task_id != report.task_id
        for event in events
    ):
        violations.append("inconsistent_run_identity")

    final_history = report.hypothesis_history
    expected_ids = [f"H{index}" for index in range(1, len(final_history) + 1)]
    if [item.hypothesis_id for item in final_history] != expected_ids or len(
        final_history
    ) > 3:
        violations.append("invalid_hypothesis_budget")
    immutable = {
        item.hypothesis_id: item.model_dump(exclude={"status"})
        for item in final_history
    }
    previous_ids: list[str] = []
    terminal: dict[str, str] = {}
    for event in events:
        history = event.hypothesis_history
        ids = [item.hypothesis_id for item in history]
        if ids != expected_ids[: len(ids)] or len(ids) < len(previous_ids):
            violations.append("history_not_append_only")
        previous_ids = ids
        if sum(item.status in _ACTIVE for item in history) > 1:
            violations.append("multiple_active_hypotheses")
        for item in history:
            if immutable.get(item.hypothesis_id) != item.model_dump(
                exclude={"status"}
            ):
                violations.append("hypothesis_identity_changed")
            prior = terminal.get(item.hypothesis_id)
            if prior is not None and item.status != prior:
                violations.append("terminal_hypothesis_revived")
            if item.status in _TERMINAL:
                terminal[item.hypothesis_id] = item.status

    evidence_ids = {item.evidence_id for item in report.evidence}
    if len(evidence_ids) != len(report.evidence):
        violations.append("duplicate_evidence_id")
    for index, hypothesis in enumerate(final_history):
        if index == 0 and hypothesis.evidence_basis:
            violations.append("h1_has_evidence_basis")
        if index and (
            not hypothesis.evidence_basis
            or not set(hypothesis.evidence_basis).issubset(evidence_ids)
        ):
            violations.append("invalid_reformulation_evidence_basis")
        if index:
            prior_ids = {item.hypothesis_id for item in final_history[:index]}
            basis = [
                item
                for item in report.evidence
                if item.evidence_id in hypothesis.evidence_basis
            ]
            if any(item.hypothesis_id not in prior_ids for item in basis):
                violations.append("invalid_reformulation_evidence_basis")
    for evidence in report.evidence:
        try:
            audit_evidence(evidence, report.observations, events, directory)
        except (OSError, ValueError):
            violations.append("invalid_evidence_provenance")

    tool_events = [event for event in events if event.event_type == "tool_executed"]
    validation_events = [
        event for event in events if event.event_type == "validation_completed"
    ]
    if len(tool_events) + len(validation_events) > manifest.tool_call_limit:
        violations.append("tool_budget_exceeded")
    per_hypothesis: dict[str, int] = {}
    for event in tool_events:
        experiment, result = event.experiment, event.tool_result
        active = [item for item in event.hypothesis_history if item.status in _ACTIVE]
        if (
            experiment is None
            or result is None
            or len(active) != 1
            or experiment.hypothesis_id != active[0].hypothesis_id
            or result.hypothesis_id != experiment.hypothesis_id
            or result.experiment_id != experiment.experiment_id
            or result.tool_name != experiment.tool_name
        ):
            violations.append("invalid_experiment_binding")
            continue
        per_hypothesis[experiment.hypothesis_id] = (
            per_hypothesis.get(experiment.hypothesis_id, 0) + 1
        )
    if any(count > 3 for count in per_hypothesis.values()):
        violations.append("experiment_budget_exceeded")

    reformulations = [
        event for event in events if event.event_type == "hypothesis_reformulated"
    ]
    if len(reformulations) != max(0, len(final_history) - 1):
        violations.append("invalid_reformulation_history")
    evidence_sequence = {
        event.evidence.evidence_id: event.sequence
        for event in events
        if event.event_type == "evidence_recorded" and event.evidence is not None
    }
    for event in reformulations:
        history = event.hypothesis_history
        if len(history) < 2 or history[-2].status not in {"rejected", "inconclusive"}:
            violations.append("reformulated_before_current_hypothesis_ended")
            continue
        new_hypothesis = history[-1]
        prior_ids = {item.hypothesis_id for item in history[:-1]}
        basis = [
            item
            for item in report.evidence
            if item.evidence_id in new_hypothesis.evidence_basis
        ]
        if (
            len(basis) != len(new_hypothesis.evidence_basis)
            or any(item.hypothesis_id not in prior_ids for item in basis)
            or any(
                evidence_sequence.get(item.evidence_id, event.sequence)
                >= event.sequence
                for item in basis
            )
        ):
            violations.append("invalid_reformulation_evidence_basis")

    evidence_by_id = {item.evidence_id: item for item in report.evidence}
    assessment_outcomes = {
        "falsified": "rejected",
        "sufficiently_supported": "supported",
        "inconclusive": "inconclusive",
    }
    for event in [
        item for item in events if item.event_type == "hypothesis_assessed"
    ]:
        try:
            if not event.model_response_artifact:
                raise ValueError("assessment lacks model artifact")
            decision = HypothesisAssessmentDecision.model_validate(
                _read_json_artifact(directory, event.model_response_artifact)
            )
            referenced = [evidence_by_id[item] for item in decision.evidence_refs]
            if any(
                evidence_sequence.get(item.evidence_id, event.sequence)
                >= event.sequence
                for item in referenced
            ):
                raise ValueError("assessment references future Evidence")
            if len({item.hypothesis_id for item in referenced}) != 1:
                raise ValueError("assessment Evidence crosses Hypotheses")
            hypothesis_id = referenced[0].hypothesis_id
            assessed = next(
                item
                for item in event.hypothesis_history
                if item.hypothesis_id == hypothesis_id
            )
            expected_status = assessment_outcomes.get(decision.outcome)
            if expected_status is not None and assessed.status != expected_status:
                raise ValueError("assessment outcome differs from lifecycle")
            if (
                decision.outcome == "continue_testing"
                and assessed.status not in _ACTIVE
            ):
                raise ValueError("continue_testing requires an Active Hypothesis")
            expected_direction = (
                "contradicting"
                if decision.outcome == "falsified"
                else "supporting"
                if decision.outcome == "sufficiently_supported"
                else None
            )
            if expected_direction and not any(
                item.direction == expected_direction for item in referenced
            ):
                raise ValueError("assessment Evidence direction is incompatible")
        except (OSError, ValueError, KeyError, StopIteration):
            violations.append("invalid_hypothesis_assessment")

    for event in [
        item
        for item in events
        if item.event_type in {"patch_generated", "validation_completed"}
    ]:
        supported = [
            item for item in event.hypothesis_history if item.status == "supported"
        ]
        expected_id = supported[0].hypothesis_id if len(supported) == 1 else None
        bindings = [
            value
            for value in (
                event.patch.hypothesis_id if event.patch is not None else None,
                event.validation.hypothesis_id
                if event.validation is not None
                else None,
                event.validation_action.hypothesis_id
                if event.validation_action is not None
                else None,
                event.tool_result.hypothesis_id
                if event.tool_result is not None
                else None,
            )
            if value is not None
        ]
        action_matches_patch = (
            event.patch is not None
            and event.validation_action is not None
            and event.validation_action.tool_name == "apply_patch"
            and event.validation_action.arguments
            == {
                "target_path": event.patch.target_path,
                "unified_diff": event.patch.unified_diff,
            }
        )
        result_matches_action = (
            event.tool_result is None
            or (
                event.validation_action is not None
                and event.tool_result.tool_name == "apply_patch"
                and event.tool_result.validation_action_id
                == event.validation_action.validation_action_id
            )
        )
        if (
            expected_id is None
            or not bindings
            or any(item != expected_id for item in bindings)
            or not action_matches_patch
            or not result_matches_action
            or event.patch != report.patch
            or (
                event.event_type == "validation_completed"
                and event.validation != report.validation
            )
        ):
            violations.append("non_supported_hypothesis_patch")

    final_event_type = (
        "run_failed" if report.status == "failed" else "run_completed"
    )
    if not events or events[-1].event_type != final_event_type:
        violations.append("illegal_stop_event")
    if not _legal_stop(
        report,
        events,
        tool_call_count=len(tool_events) + len(validation_events),
        tool_call_limit=manifest.tool_call_limit,
    ):
        violations.append("illegal_stop_reason")
    return TrajectoryEvaluation(
        passed=not violations,
        violations=tuple(dict.fromkeys(violations)),
    )


def _legal_stop(
    report: object,
    events: list[DiagnosisEvent],
    *,
    tool_call_count: int,
    tool_call_limit: int,
) -> bool:
    from .contracts import DiagnosisReport

    assert isinstance(report, DiagnosisReport)
    if report.status == "in_progress":
        return report.stop_reason is None
    if report.status == "failed":
        if report.stop_reason in {"schema_failure", "infrastructure_failure"}:
            return bool(events) and events[-1].failure_category == report.stop_reason
        if report.stop_reason == "tool_failure":
            return any(
                event.tool_result is not None and event.tool_result.status == "error"
                for event in events
            )
        return False
    if report.stop_reason == "validation_passed":
        return report.validation is not None and report.validation.status == "passed"
    if report.stop_reason == "validation_failed":
        return report.validation is not None and report.validation.status == "failed"
    if report.stop_reason == "read_only_diagnosis_complete":
        return (
            report.final_hypothesis is not None
            and report.final_hypothesis.status == "supported"
            and report.patch is None
        )
    if report.stop_reason == "hypothesis_budget_exhausted":
        return (
            len(report.hypothesis_history) == 3
            and report.final_hypothesis is not None
            and report.final_hypothesis.status in {"rejected", "inconclusive"}
        )
    return (
        report.stop_reason == "tool_budget_exhausted"
        and tool_call_count == tool_call_limit
    )


def _search_capability(
    directory: Path,
    report: object,
    events: list[DiagnosisEvent],
    trajectory: TrajectoryEvaluation,
) -> SearchCapability:
    from .contracts import DiagnosisReport
    from .tool_runtime import SearchCodeResult

    assert isinstance(report, DiagnosisReport)
    if "invalid_evidence_provenance" in trajectory.violations:
        return "invalid_trajectory"

    used_evidence = {
        evidence_id
        for hypothesis in report.hypothesis_history
        for evidence_id in hypothesis.evidence_basis
    }
    if report.root_cause_analysis is not None and report.root_cause_analysis.location:
        used_evidence.update(report.root_cause_analysis.location.evidence_refs)
    for event in events:
        if (
            event.event_type != "hypothesis_assessed"
            or not event.model_response_artifact
        ):
            continue
        try:
            decision = HypothesisAssessmentDecision.model_validate(
                _read_json_artifact(directory, event.model_response_artifact)
            )
            used_evidence.update(decision.evidence_refs)
        except (OSError, ValueError, KeyError, IndexError, TypeError):
            return "invalid_trajectory"

    observations = {item.observation_id: item for item in report.observations}
    for evidence in report.evidence:
        observation = observations.get(evidence.observation_ref)
        if observation is None or observation.source != "search_code":
            continue
        try:
            audit_evidence(evidence, report.observations, events, directory)
            result = SearchCodeResult.model_validate_json(
                artifact_path(directory, observation.artifact_ref).read_text()
            )
        except (OSError, ValueError):
            return "invalid_trajectory"
        if (
            evidence.evidence_id in used_evidence
            and result.status == "matched"
            and result.matches
        ):
            return "verified"
    return "not_demonstrated"


def evaluate_run(
    run_directory: Path,
    ground_truth: EvaluationGroundTruth,
    *,
    causal_review: CausalReviewRecord | None = None,
) -> TaskEvaluationResult:
    """Evaluate one persisted run without feeding evaluation data to the Agent."""

    directory = Path(run_directory)
    manifest = TaskManifest.model_validate_json(
        artifact_path(directory, "manifest.json").read_text()
    )
    if manifest != load_frozen_manifest(ground_truth.task_id):
        raise ValueError("Run Manifest differs from the canonical frozen task")
    report = read_persisted_report(
        json.loads(artifact_path(directory, "report.json").read_text())
    )
    events, event_contract_violations = _read_events(directory)
    if manifest.task_id != ground_truth.task_id or report.task_id != manifest.task_id:
        raise ValueError("Run, Manifest, and Ground Truth task IDs differ")
    outcome = _outcome(directory, manifest, ground_truth, report, events)
    trajectory = _trajectory(
        directory,
        manifest,
        report,
        events,
        event_contract_violations,
    )
    review = causal_review or CausalReviewRecord.pending(ground_truth.task_id)
    if review.task_id != ground_truth.task_id:
        raise ValueError("Causal Review task ID differs from Ground Truth")
    search = _search_capability(directory, report, events, trajectory)
    return TaskEvaluationResult(
        task_id=ground_truth.task_id,
        run_id=report.run_id,
        run_directory=str(directory),
        outcome=outcome,
        trajectory=trajectory,
        search_capability=search,
        causal_review=review,
        accepted=outcome.passed and trajectory.passed and review.status == "passed",
    )
