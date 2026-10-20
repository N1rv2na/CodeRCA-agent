"""Public contracts for CodeRCA Diagnosis Tasks and Diagnosis Runs."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

NonEmptyString = Annotated[str, StringConstraints(min_length=1)]
TestFailureExitCode = Annotated[int, Field(ge=1, le=124)]
DiagnosisFailureCategory = Literal["schema_failure", "infrastructure_failure"]
DiagnosisStopReason = (
    DiagnosisFailureCategory
    | Literal[
        "read_only_diagnosis_complete",
        "hypothesis_budget_exhausted",
        "tool_budget_exhausted",
        "tool_failure",
        "validation_passed",
        "validation_failed",
    ]
)
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
ToolErrorCategory = Literal[
    "invalid_arguments", "permission_denied", "timeout", "execution_failed"
]
HypothesisAssessmentOutcome = Literal[
    "continue_testing", "falsified", "sufficiently_supported", "inconclusive"
]


class DecisionValidationError(ValueError):
    """A structured model decision violates current runtime/domain constraints."""

    def __init__(
        self, message: str, validation_errors: list[dict[str, object]]
    ) -> None:
        super().__init__(message)
        self.validation_errors = validation_errors


class DiagnosisStage(str, Enum):
    """Program-owned lifecycle stage for one Diagnosis Run."""

    PREPARING = "preparing"
    FORMING_HYPOTHESIS = "forming_hypothesis"
    DIAGNOSING = "diagnosing"
    EXECUTING_TOOL = "executing_tool"
    UPDATING_EVIDENCE = "updating_evidence"
    VALIDATING = "validating"
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
    tool_call_limit: int = Field(ge=1, le=10)


class RegisteredTestCommand(ContractModel):
    """Author-owned argv that a Diagnosis Task permits `run_tests` to execute."""

    schema_version: Literal["1"]
    command_id: NonEmptyString
    argv: tuple[NonEmptyString, ...] = Field(min_length=1)
    static_check_argv: tuple[NonEmptyString, ...] = ()
    timeout_seconds: int = Field(ge=1, le=300)
    test_failure_exit_codes: tuple[TestFailureExitCode, ...] = (1,)
    test_failure_output_markers: tuple[NonEmptyString, ...] = ()

    @model_validator(mode="after")
    def require_unique_test_failure_exit_codes(self) -> RegisteredTestCommand:
        if len(set(self.test_failure_exit_codes)) != len(self.test_failure_exit_codes):
            raise ValueError("test failure exit codes must be unique")
        if len(set(self.test_failure_output_markers)) != len(
            self.test_failure_output_markers
        ):
            raise ValueError("test failure output markers must be unique")
        return self


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


class PatchValidationAction(ContractModel):
    """One program-controlled patch application and Public Validation action."""

    validation_action_id: NonEmptyString
    hypothesis_id: NonEmptyString
    purpose: NonEmptyString
    tool_name: Literal["apply_patch"]
    arguments: dict[str, Any]


class SelectExperimentDecision(ContractModel):
    """Model-selected Experiment before program ID assignment."""

    hypothesis_id: NonEmptyString
    purpose: NonEmptyString
    expected_observation: NonEmptyString
    falsification_relevance: NonEmptyString
    tool_name: NonEmptyString
    arguments: dict[str, Any]


class ToolResult(ContractModel):
    """Auditable result of one Tool Runtime invocation."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False, frozen=True)

    tool_result_id: NonEmptyString
    experiment_id: NonEmptyString | None = None
    validation_action_id: NonEmptyString | None = None
    hypothesis_id: NonEmptyString
    tool_name: NonEmptyString
    status: Literal["success", "error"]
    output: str = ""
    artifact_ref: NonEmptyString
    truncated: bool = False
    duration_ms: int = Field(ge=0)
    error_category: ToolErrorCategory | None = None
    error_message: str | None = None
    command_id: NonEmptyString | None = None
    exit_code: int | None = None

    @model_validator(mode="after")
    def require_consistent_status(self) -> ToolResult:
        if (self.experiment_id is None) == (self.validation_action_id is None):
            raise ValueError(
                "Tool Result requires exactly one Experiment or Validation Action ID"
            )
        if self.status == "success" and (
            self.error_category is not None or self.error_message is not None
        ):
            raise ValueError("successful Tool Result cannot contain an error")
        if self.status == "error" and (
            self.error_category is None or not self.error_message
        ):
            raise ValueError("failed Tool Result requires a classified error")
        if (
            self.tool_name == "run_tests"
            and self.status == "success"
            and (self.command_id is None or self.exit_code is None)
        ):
            raise ValueError(
                "successful run_tests Tool Result requires command ID and exit code"
            )
        return self


class Observation(ContractModel):
    """A structured, artifact-backed result produced by a controlled action."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    observation_id: NonEmptyString
    experiment_id: NonEmptyString | None = None
    validation_action_id: NonEmptyString | None = None
    hypothesis_id: NonEmptyString
    tool_result_ref: NonEmptyString
    source: NonEmptyString
    summary: NonEmptyString
    artifact_ref: NonEmptyString
    excerpt: str = ""

    @model_validator(mode="after")
    def require_one_action_reference(self) -> Observation:
        if (self.experiment_id is None) == (self.validation_action_id is None):
            raise ValueError(
                "Observation requires exactly one Experiment or Validation Action ID"
            )
        return self


class Evidence(ContractModel):
    """A qualitative interpretation of one Observation for one Hypothesis."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    evidence_id: NonEmptyString
    hypothesis_id: NonEmptyString
    observation_ref: NonEmptyString
    provenance: NonEmptyString
    direction: EvidenceDirection
    explanation: NonEmptyString


class UpdateEvidenceDecision(ContractModel):
    """Model interpretation of one real Observation before program IDs it."""

    hypothesis_id: NonEmptyString
    observation_ref: NonEmptyString
    direction: EvidenceDirection = Field(
        description=(
            "Direction relative to the Active Hypothesis mechanism, NOT its "
            "falsification criterion or expected_observation. supporting: observed "
            "facts positively support that mechanism; contradicting: observed facts "
            "oppose that mechanism; inconclusive: insufficient, mixed, or ambiguous. "
            "Failure to falsify alone is not supporting evidence."
        )
    )
    explanation: NonEmptyString = Field(
        description=(
            "State observed facts, their relation to the unchanged Hypothesis "
            "mechanism, and limitations. The selected direction must agree with "
            "this explanation; do not label support for the mechanism contradicting "
            "merely because it contradicts a falsification condition."
        )
    )


class HypothesisAssessmentDecision(ContractModel):
    """A model proposal that the program maps to a legal lifecycle transition."""

    outcome: HypothesisAssessmentOutcome
    evidence_refs: tuple[NonEmptyString, ...] = Field(min_length=1)
    rationale: NonEmptyString


class ExactReplacement(ContractModel):
    """One literal source replacement within a model-proposed Patch Intent."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False, frozen=True)

    old_text: NonEmptyString
    new_text: str

    @model_validator(mode="after")
    def reject_no_op_replacement(self) -> ExactReplacement:
        if self.old_text == self.new_text:
            raise ValueError("exact replacement must change its source text")
        return self


class PatchIntentDecision(ContractModel):
    """A model-proposed repair intent bound to one supported Hypothesis."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False, frozen=True)

    hypothesis_id: NonEmptyString
    target_path: NonEmptyString
    mechanism: NonEmptyString
    edits: tuple[ExactReplacement, ...] = Field(min_length=1, max_length=3)

    @field_validator("hypothesis_id", "target_path", "mechanism", mode="before")
    @classmethod
    def normalize_metadata(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class CandidatePatch(ContractModel):
    """One program-compiled patch bound to one supported Hypothesis."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False, frozen=True)

    hypothesis_id: NonEmptyString
    target_path: NonEmptyString
    mechanism: NonEmptyString
    unified_diff: NonEmptyString

    @field_validator("hypothesis_id", "target_path", "mechanism", mode="before")
    @classmethod
    def normalize_metadata(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class FinalRootCauseLocation(ContractModel):
    """Evidence-backed location in Faulty Commit coordinates, not an initial guess."""

    path: NonEmptyString
    symbol: NonEmptyString | None
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    evidence_refs: tuple[NonEmptyString, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_location(self) -> FinalRootCauseLocation:
        if (
            self.path.startswith("/")
            or "\\" in self.path
            or any(part in {"", ".", ".."} for part in self.path.split("/"))
        ):
            raise ValueError("location path must be canonical repository-relative")
        if self.end_line < self.start_line:
            raise ValueError("location line range is reversed")
        if len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ValueError("location Evidence references must be unique")
        return self


class ReportDecision(ContractModel):
    """Model-authored causal fields for the final Root Cause Report."""

    trigger_condition: NonEmptyString
    propagation_path: NonEmptyString
    failure_manifestation: NonEmptyString
    repair_recommendation: NonEmptyString
    location: FinalRootCauseLocation | None


class ValidationCheckResult(ContractModel):
    """One artifact-backed check within Public Validation."""

    name: Literal["static_check", "registered_test"]
    passed: bool
    exit_code: int
    artifact_ref: NonEmptyString


class PublicValidationResult(ContractModel):
    """Terminal result of applying one patch in an isolated workspace."""

    hypothesis_id: NonEmptyString
    status: Literal["passed", "failed"]
    patch_artifact_ref: NonEmptyString
    artifact_ref: NonEmptyString
    static_check: ValidationCheckResult | None = None
    registered_test: ValidationCheckResult | None = None
    failure_category: ToolErrorCategory | None = None
    failure_message: NonEmptyString | None = None

    @model_validator(mode="after")
    def require_consistent_validation_status(self) -> PublicValidationResult:
        if self.status == "passed":
            if self.failure_category is not None or self.failure_message is not None:
                raise ValueError("passed Validation cannot contain an error")
            if (
                self.static_check is None
                or not self.static_check.passed
                or self.registered_test is None
                or not self.registered_test.passed
            ):
                raise ValueError("passed Validation requires both checks to pass")
        elif not self.failure_message:
            raise ValueError("failed Validation requires a failure message")
        return self


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
    experiment: Experiment | None = None
    validation_action: PatchValidationAction | None = None
    tool_result: ToolResult | None = None
    observation: Observation | None = None
    evidence: Evidence | None = None
    patch: CandidatePatch | None = None
    validation: PublicValidationResult | None = None
    root_cause_analysis: ReportDecision | None = None


class DiagnosisReport(ContractModel):
    run_id: NonEmptyString
    task_id: NonEmptyString
    stage: DiagnosisStage
    status: Literal["in_progress", "completed", "failed"]
    stop_reason: DiagnosisStopReason | None = None
    summary: NonEmptyString
    hypothesis_history: list[Hypothesis] = Field(default_factory=list)
    final_hypothesis: Hypothesis | None = None
    observations: list[Observation] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    patch: CandidatePatch | None = None
    validation: PublicValidationResult | None = None
    root_cause_analysis: ReportDecision | None = None


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
    status: Literal["in_progress", "completed", "failed"]
    stop_reason: DiagnosisStopReason | None = None
    summary: NonEmptyString
    hypothesis_history: tuple[Hypothesis, ...] = ()
    observations: tuple[Observation, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    patch: CandidatePatch | None = None
    validation: PublicValidationResult | None = None
    root_cause_analysis: ReportDecision | None = None
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
