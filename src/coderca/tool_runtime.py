"""Typed, bounded runtime for CRCA-005 read-only diagnosis tools."""

from __future__ import annotations

import subprocess
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .contracts import (
    DecisionValidationError,
    Experiment,
    TaskManifest,
    ToolErrorCategory,
    ToolResult,
)

_MAX_READ_LINES = 200
_DEFAULT_RESULT_LIMIT = 12_000


class ToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class InspectDiffArguments(ToolArguments):
    path: str | None = None


class ReadCodeArguments(ToolArguments):
    path: str = Field(min_length=1)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_line_range(self) -> ReadCodeArguments:
        if self.end_line < self.start_line:
            raise ValueError("end_line must be greater than or equal to start_line")
        if self.end_line - self.start_line + 1 > _MAX_READ_LINES:
            raise ValueError(f"read_code is limited to {_MAX_READ_LINES} lines")
        return self


ToolHandler = Callable[[BaseModel, float], str]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    version: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    permission: Literal["read_only"]
    timeout_seconds: float
    result_limit: int
    side_effects: Literal["none"]
    error_categories: tuple[ToolErrorCategory, ...]
    handler: ToolHandler

    @property
    def input_schema(self) -> dict[str, object]:
        return self.input_model.model_json_schema()

    @property
    def output_schema(self) -> dict[str, object]:
        return self.output_model.model_json_schema()


class ToolRuntime:
    """Validate, execute, classify, bound, and persist Tool Results."""

    def __init__(
        self,
        workspace_root: Path,
        manifest: TaskManifest,
        *,
        enforce_faulty_commit: bool = True,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.manifest = manifest
        if not self.workspace_root.is_dir():
            raise ValueError("Tool Runtime workspace must be a directory")
        if enforce_faulty_commit:
            self._verify_faulty_commit()
        self._call_count = 0
        self.tool_specs = {
            "inspect_diff": ToolSpec(
                name="inspect_diff",
                version="1",
                description="Inspect the base-to-faulty Git diff.",
                input_model=InspectDiffArguments,
                output_model=ToolResult,
                permission="read_only",
                timeout_seconds=10,
                result_limit=_DEFAULT_RESULT_LIMIT,
                side_effects="none",
                error_categories=(
                    "invalid_arguments",
                    "permission_denied",
                    "timeout",
                    "execution_failed",
                ),
                handler=self._inspect_diff,
            ),
            "read_code": ToolSpec(
                name="read_code",
                version="1",
                description="Read a bounded line range from repository source.",
                input_model=ReadCodeArguments,
                output_model=ToolResult,
                permission="read_only",
                timeout_seconds=5,
                result_limit=_DEFAULT_RESULT_LIMIT,
                side_effects="none",
                error_categories=(
                    "invalid_arguments",
                    "permission_denied",
                    "timeout",
                    "execution_failed",
                ),
                handler=self._read_code,
            ),
        }

    def available_tool_catalog(self) -> list[dict[str, Any]]:
        """Project registered Tool Specs into a deterministic model-safe view."""

        return [
            {
                "name": spec.name,
                "description": spec.description,
                "input_schema": spec.input_schema,
                "permission": spec.permission,
                "side_effects": spec.side_effects,
                "timeout_seconds": spec.timeout_seconds,
                "result_limit": spec.result_limit,
            }
            for spec in (
                self.tool_specs[name] for name in sorted(self.tool_specs)
            )
        ]

    def validate_selection(
        self, tool_name: str, arguments: dict[str, object]
    ) -> None:
        """Validate a model-selected call before state or budget mutation."""

        spec = self.tool_specs.get(tool_name)
        if spec is None:
            raise DecisionValidationError(
                f"tool {tool_name!r} is not registered",
                [
                    {
                        "loc": ["tool_name"],
                        "type": "tool_not_registered",
                        "msg": "Tool name is not registered.",
                        "input": tool_name,
                        "allowed_tools": sorted(self.tool_specs),
                    }
                ],
            )
        try:
            spec.input_model.model_validate(arguments)
        except ValidationError as exc:
            errors = [
                {
                    "loc": ["arguments", *item["loc"]],
                    "type": item["type"],
                    "msg": item["msg"],
                    "input": item.get("input"),
                }
                for item in exc.errors(include_url=False, include_context=False)
            ]
            raise DecisionValidationError(
                f"arguments for tool {tool_name!r} do not satisfy its schema",
                errors,
            ) from exc

    def _verify_faulty_commit(self) -> None:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self.workspace_root,
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ValueError(
                "Tool Runtime workspace is not a readable Git checkout"
            ) from exc
        if result.stdout.strip() != self.manifest.faulty_commit:
            raise ValueError("Tool Runtime workspace is not at the Faulty Commit")

    def execute(
        self, experiment: Experiment, *, artifact_directory: Path
    ) -> ToolResult:
        started = monotonic()
        self._call_count += 1
        tool_result_id = f"T{self._call_count}"
        spec = self.tool_specs.get(experiment.tool_name)
        error_category: ToolErrorCategory | None = None
        error_message: str | None = None
        output = ""
        result_limit = _DEFAULT_RESULT_LIMIT
        try:
            if spec is None:
                raise _ToolFailure("invalid_arguments", "unknown tool name")
            result_limit = spec.result_limit
            try:
                arguments = spec.input_model.model_validate(experiment.arguments)
            except ValidationError as exc:
                raise _ToolFailure(
                    "invalid_arguments", "tool arguments do not satisfy the schema"
                ) from exc
            output = spec.handler(arguments, spec.timeout_seconds)
        except _ToolFailure as exc:
            error_category = exc.category
            error_message = str(exc)
        except subprocess.TimeoutExpired:
            error_category = "timeout"
            error_message = "tool execution exceeded its timeout"
        except TimeoutError:
            error_category = "timeout"
            error_message = "tool execution exceeded its timeout"
        except Exception as exc:
            error_category = "execution_failed"
            error_message = f"tool execution failed: {type(exc).__name__}"

        full_artifact = output if error_category is None else error_message or ""
        artifact_directory = Path(artifact_directory)
        artifact_directory.mkdir(parents=True, exist_ok=True)
        artifact_path = artifact_directory / f"{tool_result_id}.txt"
        artifact_path.write_text(full_artifact, encoding="utf-8")
        artifact_ref = str(Path(artifact_directory.name) / artifact_path.name)
        bounded_output = output[:result_limit]
        return ToolResult(
            tool_result_id=tool_result_id,
            experiment_id=experiment.experiment_id,
            hypothesis_id=experiment.hypothesis_id,
            tool_name=experiment.tool_name,
            status="success" if error_category is None else "error",
            output=bounded_output,
            artifact_ref=artifact_ref,
            truncated=len(output) > len(bounded_output),
            duration_ms=max(int((monotonic() - started) * 1_000), 0),
            error_category=error_category,
            error_message=error_message,
        )

    def _inspect_diff(self, raw: BaseModel, timeout_seconds: float) -> str:
        arguments = InspectDiffArguments.model_validate(raw.model_dump())
        command = [
            "git",
            "diff",
            "--no-ext-diff",
            self.manifest.base_snapshot,
            self.manifest.faulty_commit,
            "--",
        ]
        if arguments.path is None:
            command.extend(self.manifest.read_paths)
        else:
            command.append(self._authorized_relative_path(arguments.path))
        result = subprocess.run(
            command,
            cwd=self.workspace_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        if result.returncode != 0:
            raise _ToolFailure("execution_failed", "git diff execution failed")
        return result.stdout

    def _read_code(self, raw: BaseModel, timeout_seconds: float) -> str:
        arguments = ReadCodeArguments.model_validate(raw.model_dump())
        relative_path = self._authorized_relative_path(arguments.path)
        unresolved_path = self.workspace_root / relative_path
        current = self.workspace_root
        for part in Path(relative_path).parts:
            current /= part
            if current.is_symlink():
                raise _ToolFailure(
                    "permission_denied", "symbolic links are not readable"
                )
        path = unresolved_path.resolve()
        try:
            resolved_relative = path.relative_to(self.workspace_root).as_posix()
        except ValueError as exc:
            raise _ToolFailure(
                "permission_denied", "path escapes the repository workspace"
            ) from exc
        self._authorized_relative_path(resolved_relative)
        if not path.is_file():
            raise _ToolFailure(
                "permission_denied", "path is not a readable repository file"
            )
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(self._read_file_text, path)
        try:
            content = future.result(timeout=timeout_seconds)
        except FutureTimeoutError as exc:
            future.cancel()
            raise TimeoutError("read_code exceeded its timeout") from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        lines = content.splitlines()
        selected = lines[arguments.start_line - 1 : arguments.end_line]
        return "".join(
            f"{line_number}: {line}\n"
            for line_number, line in enumerate(selected, arguments.start_line)
        )

    @staticmethod
    def _read_file_text(path: Path) -> str:
        return path.read_text(encoding="utf-8")

    def _authorized_relative_path(self, value: str) -> str:
        candidate = Path(value)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise _ToolFailure(
                "permission_denied", "path escapes the permitted repository scope"
            )
        normalized = candidate.as_posix()
        if not any(
            normalized == allowed.rstrip("/")
            or normalized.startswith(f"{allowed.rstrip('/')}/")
            for allowed in self.manifest.read_paths
        ):
            raise _ToolFailure(
                "permission_denied", "path is outside Manifest read_paths"
            )
        return normalized


class _ToolFailure(RuntimeError):
    def __init__(self, category: ToolErrorCategory, message: str) -> None:
        super().__init__(message)
        self.category = category
