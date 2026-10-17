"""Public contracts for CodeRCA Diagnosis Tasks and Diagnosis Runs."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

NonEmptyString = Annotated[str, StringConstraints(min_length=1)]
DiagnosisFailureCategory = Literal["schema_failure", "infrastructure_failure"]
DiagnosisEventFailureCategory = (
    DiagnosisFailureCategory
    | Literal[
        "invalid_json",
        "invalid_response",
        "schema_mismatch",
    ]
)
HypothesisStatus = Literal[
    "proposed", "testing", "supported", "rejected", "inconclusive"
]
EvidenceDirection = Literal["supporting", "contradicting", "inconclusive"]
HypothesisAssessmentOutcome = Literal[
    "continue_testing", "falsified", "sufficiently_supported", "inconclusive"
]


class DiagnosisStage(str, Enum):
    """Program-owned lifecycle stage for one Diagnosis Run."""

    PREPARING = "preparing"
    FORMING_HYPOTHESIS = "forming_hypothesis"
    DIAGNOSING = "diagnosing"
    FINALIZING = "finalizing"


class ContractModel(BaseModel):
    """Shared validation settings for externally visible contracts."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TaskManifest(ContractModel):
    """Versioned, immutable input describing one diagnosis task."""

    schema_version: Literal["1"]
    task_id: NonEmptyString
    repository_id: NonEmptyString
    base_snapshot: NonEmptyString
    faulty_commit: NonEmptyString
    ci_log: NonEmptyString
    test_command_id: NonEmptyString
    docker_image: NonEmptyString
    read_paths: list[NonEmptyString] = Field(min_length=1)
    write_paths: list[NonEmptyString]
    tool_call_limit: int = Field(ge=1, le=8)


class EvaluationGroundTruth(ContractModel):
    """Evaluation-only facts that must not enter Agent-visible task input."""

    schema_version: Literal["1"]
    task_id: NonEmptyString
    root_symbol: NonEmptyString
    trigger_condition: NonEmptyString
    defect_mechanism: NonEmptyString
    propagation_path: NonEmptyString
    failure_manifestation: NonEmptyString
    reference_repair_behavior: NonEmptyString


class HypothesisProposal(ContractModel):
    """Model-proposed, falsifiable Root Cause before program ID assignment."""

    root_symbol: NonEmptyString | None = None
    location_description: NonEmptyString | None = None
    mechanism: NonEmptyString
    falsification_criterion: NonEmptyString

    @model_validator(mode="after")
    def require_location(self) -> HypothesisProposal:
        if self.root_symbol is None and self.location_description is None:
            raise ValueError(
                "a Hypothesis requires a Root Symbol or Location Description"
            )
        return self


class FormHypothesisDecision(ContractModel):
    """One initial proposal; H1 cannot cite Evidence that does not exist yet."""

    hypothesis: HypothesisProposal


class ReformulateHypothesisDecision(ContractModel):
    """One replacement proposal citing existing Evidence by stable ID."""

    hypothesis: HypothesisProposal
    evidence_refs: tuple[NonEmptyString, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def require_unique_evidence_refs(self) -> ReformulateHypothesisDecision:
        if len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ValueError("Reformulation Evidence IDs must be unique")
        return self


class Hypothesis(HypothesisProposal):
    """One immutable, program-identified entry in Hypothesis History."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    hypothesis_id: NonEmptyString
    evidence_basis: tuple[NonEmptyString, ...] = ()
    status: HypothesisStatus = "proposed"


class Experiment(ContractModel):
    """A falsification-oriented action bound to the Active Hypothesis."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    experiment_id: NonEmptyString
    hypothesis_id: NonEmptyString
    purpose: NonEmptyString
    expected_observation: NonEmptyString
    falsification_relevance: NonEmptyString
    tool_name: NonEmptyString
    arguments: dict[str, Any]


class Observation(ContractModel):
    """A structured, artifact-backed result produced by an Experiment."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    observation_id: NonEmptyString
    experiment_id: NonEmptyString
    hypothesis_id: NonEmptyString
    source: NonEmptyString
    summary: NonEmptyString
    artifact_ref: NonEmptyString
    excerpt: str = ""


class Evidence(ContractModel):
    """A qualitative interpretation of one Observation for one Hypothesis."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    evidence_id: NonEmptyString
    hypothesis_id: NonEmptyString
    observation_ref: NonEmptyString
    provenance: NonEmptyString
    direction: EvidenceDirection
    explanation: NonEmptyString


class HypothesisAssessmentDecision(ContractModel):
    """A model proposal that the program maps to a legal lifecycle transition."""

    outcome: HypothesisAssessmentOutcome
    evidence_refs: tuple[NonEmptyString, ...] = Field(min_length=1)
    rationale: NonEmptyString


class DiagnosisEvent(ContractModel):
    sequence: int = Field(ge=1)
    event_type: NonEmptyString
    run_id: NonEmptyString
    task_id: NonEmptyString
    stage: DiagnosisStage
    message: NonEmptyString
    hypothesis_history: list[Hypothesis] = Field(default_factory=list)
    model_response_artifact: NonEmptyString | None = None
    failure_category: DiagnosisEventFailureCategory | None = None
    validation_errors: list[dict[str, Any]] = Field(default_factory=list)


class DiagnosisReport(ContractModel):
    run_id: NonEmptyString
    task_id: NonEmptyString
    stage: DiagnosisStage
    status: Literal["in_progress", "failed"]
    stop_reason: DiagnosisFailureCategory | None = None
    summary: NonEmptyString
    hypothesis_history: list[Hypothesis] = Field(default_factory=list)


class RunArtifacts(ContractModel):
    run_directory: Path
    manifest_path: Path
    events_path: Path
    report_path: Path
    model_responses_directory: Path


class DiagnosisRunResult(ContractModel):
    run_id: NonEmptyString
    task_id: NonEmptyString
    stage: DiagnosisStage
    status: Literal["in_progress", "failed"]
    stop_reason: DiagnosisFailureCategory | None = None
    summary: NonEmptyString
    hypothesis_history: tuple[Hypothesis, ...] = ()
    run_directory: Path
    manifest_path: Path
    events_path: Path
    report_path: Path


class StructuredError(ContractModel):
    code: NonEmptyString
    message: NonEmptyString
    details: Any


class CliError(ContractModel):
    error: StructuredError
