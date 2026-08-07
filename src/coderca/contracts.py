"""Public contracts for the CRCA-001 walking skeleton."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

NonEmptyString = Annotated[str, StringConstraints(min_length=1)]


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


class ModelCompletion(ContractModel):
    """The narrow result returned by an external model boundary."""

    stage: Literal["finalizing"] = "finalizing"
    status: Literal["completed"] = "completed"
    stop_reason: Literal["fake_model_completed"] = "fake_model_completed"
    summary: NonEmptyString


class DiagnosisEvent(ContractModel):
    sequence: int = Field(ge=1)
    event_type: NonEmptyString
    run_id: NonEmptyString
    task_id: NonEmptyString
    stage: NonEmptyString
    message: NonEmptyString


class DiagnosisReport(ContractModel):
    run_id: NonEmptyString
    task_id: NonEmptyString
    stage: Literal["finalizing"]
    status: Literal["completed"]
    stop_reason: Literal["fake_model_completed"]
    summary: NonEmptyString
    root_cause_candidates: list[Any] = Field(default_factory=list)


class RunArtifacts(ContractModel):
    run_directory: Path
    manifest_path: Path
    events_path: Path
    report_path: Path

    @property
    def directory(self) -> Path:
        """Backward-friendly alias for the run directory."""

        return self.run_directory


class DiagnosisRunResult(ContractModel):
    run_id: NonEmptyString
    task_id: NonEmptyString
    stage: Literal["finalizing"]
    status: Literal["completed"]
    stop_reason: Literal["fake_model_completed"]
    summary: NonEmptyString
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
