"""Typed, bounded runtime for CodeRCA diagnosis tools."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Any, Callable, Literal
from uuid import uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from .contracts import (
    DecisionValidationError,
    Experiment,
    PatchDecision,
    PatchValidationAction,
    PublicValidationResult,
    RegisteredTestCommand,
    TaskManifest,
    ToolErrorCategory,
    ToolResult,
    ValidationCheckResult,
)

_MAX_READ_LINES = 200
_DEFAULT_RESULT_LIMIT = 12_000
_MAX_SEARCH_QUERY_LENGTH = 200
_MAX_SEARCH_PATH_LENGTH = 500
_MAX_SEARCH_RESULTS = 20
_MAX_SEARCH_CONTEXT_LINES = 5
_MAX_SEARCH_SNIPPET_LENGTH = 2_000
_SEARCH_ANSWER_NAMES = frozenset(
    {
        "answer",
        "answers",
        "fixed",
        "fixed_code",
        "ground-truth",
        "ground_truth",
        "reference-patch",
        "reference_patch",
        "repaired",
        "repaired_code",
        "solution",
    }
)


def load_registered_test_command(
    path: Path, *, expected_command_id: str
) -> RegisteredTestCommand:
    """Load one author-owned argv registry and bind it to the Task Manifest ID."""

    try:
        command = RegisteredTestCommand.model_validate_json(
            Path(path).read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, ValidationError) as exc:
        raise ValueError(
            "registered test command does not satisfy its contract"
        ) from exc
    if command.command_id != expected_command_id:
        raise ValueError(
            "registered test command ID does not match the Task Manifest"
        )
    return command


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


class SearchCodeInput(ToolArguments):
    query: str = Field(min_length=1, max_length=_MAX_SEARCH_QUERY_LENGTH)
    search_kind: Literal["content", "path"]
    path: str | None = Field(
        default=None, min_length=1, max_length=_MAX_SEARCH_PATH_LENGTH
    )
    max_results: int = Field(default=10, ge=1, le=_MAX_SEARCH_RESULTS)
    context_lines: int = Field(default=2, ge=0, le=_MAX_SEARCH_CONTEXT_LINES)

    @field_validator("query")
    @classmethod
    def validate_literal_query(cls, value: str) -> str:
        if any(character in value for character in ("\0", "\r", "\n")):
            raise ValueError("query must be one bounded literal line")
        return value

    @field_validator("path")
    @classmethod
    def validate_path_scope(cls, value: str | None) -> str | None:
        if value is not None and any(
            character in value for character in ("\0", "\r", "\n")
        ):
            raise ValueError("path must be one bounded repository-relative path")
        return value


class SearchMatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    snippet: str
    truncated: bool


class SearchCodeResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    query: str
    search_kind: Literal["content", "path"]
    path: str | None
    status: Literal["matched", "no_matches"]
    matches: tuple[SearchMatch, ...]
    truncated: bool


class RunTestsArguments(ToolArguments):
    test_command_id: str = Field(min_length=1)


class ApplyPatchArguments(ToolArguments):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    target_path: str = Field(min_length=1)
    unified_diff: str = Field(min_length=1)


@dataclass(frozen=True)
class _ToolExecutionOutput:
    content: str
    artifact_content: str | None = None
    command_id: str | None = None
    exit_code: int | None = None


ToolHandler = Callable[[BaseModel, float], str | _ToolExecutionOutput]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    version: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    permission: Literal["read_only", "code_execution"]
    timeout_seconds: float
    result_limit: int
    side_effects: Literal["none", "temporary_workspace"]
    error_categories: tuple[ToolErrorCategory, ...]
    handler: ToolHandler | None

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
        registered_test_command: RegisteredTestCommand | None = None,
        enforce_faulty_commit: bool = True,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.manifest = manifest
        self._enforce_faulty_commit = enforce_faulty_commit
        if not self.workspace_root.is_dir():
            raise ValueError("Tool Runtime workspace must be a directory")
        if enforce_faulty_commit:
            self._verify_faulty_commit()
        if (
            registered_test_command is not None
            and registered_test_command.command_id != manifest.test_command_id
        ):
            raise ValueError(
                "registered test command ID does not match the Task Manifest"
            )
        self.registered_test_command = registered_test_command
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
            "search_code": ToolSpec(
                name="search_code",
                version="1",
                description=(
                    "Search repository code or paths using bounded literal "
                    "matching. Results discover locations; they do not assert "
                    "a Root Symbol or Evidence direction."
                ),
                input_model=SearchCodeInput,
                output_model=SearchCodeResult,
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
                handler=self._search_code,
            ),
            "apply_patch": ToolSpec(
                name="apply_patch",
                version="1",
                description=(
                    "Apply one candidate patch in the isolated Public Validation "
                    "workspace."
                ),
                input_model=ApplyPatchArguments,
                output_model=PublicValidationResult,
                permission="code_execution",
                timeout_seconds=10,
                result_limit=_DEFAULT_RESULT_LIMIT,
                side_effects="temporary_workspace",
                error_categories=(
                    "invalid_arguments",
                    "permission_denied",
                    "timeout",
                    "execution_failed",
                ),
                handler=None,
            ),
        }
        if registered_test_command is not None:
            self.tool_specs["run_tests"] = ToolSpec(
                name="run_tests",
                version="1",
                description=(
                    "Run the Task Manifest's registered test command in the "
                    "minimal Docker execution boundary."
                ),
                input_model=RunTestsArguments,
                output_model=ToolResult,
                permission="code_execution",
                timeout_seconds=float(registered_test_command.timeout_seconds),
                result_limit=_DEFAULT_RESULT_LIMIT,
                side_effects="temporary_workspace",
                error_categories=(
                    "invalid_arguments",
                    "permission_denied",
                    "timeout",
                    "execution_failed",
                ),
                handler=self._run_tests,
            )

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
                self.tool_specs[name]
                for name in sorted(self.tool_specs)
                if name != "apply_patch"
            )
        ]

    def execute_patch_validation(
        self,
        action: PatchValidationAction,
        patch: PatchDecision,
        *,
        artifact_directory: Path,
    ) -> tuple[ToolResult, PublicValidationResult]:
        """Apply one patch to a temporary copy and run Public Validation."""

        if (
            action.hypothesis_id != patch.hypothesis_id
            or action.tool_name != "apply_patch"
        ):
            raise ValueError(
                "Patch Validation Action must bind the candidate patch"
            )

        started = monotonic()
        self._call_count += 1
        tool_result_id = f"T{self._call_count}"
        root = Path(artifact_directory)
        patch_path = root / "patches" / "candidate.patch"
        validation_path = root / "validation" / "result.json"
        patch_path.parent.mkdir(parents=True, exist_ok=True)
        validation_path.parent.mkdir(parents=True, exist_ok=True)
        unified_diff = (
            patch.unified_diff
            if patch.unified_diff.endswith("\n")
            else patch.unified_diff + "\n"
        )
        patch_path.write_text(unified_diff, encoding="utf-8")
        patch_ref = patch_path.relative_to(root).as_posix()
        validation_ref = validation_path.relative_to(root).as_posix()

        static_check: ValidationCheckResult | None = None
        registered_test: ValidationCheckResult | None = None
        failure_category: ToolErrorCategory | None = None
        failure_message: str | None = None
        try:
            spec = self.tool_specs["apply_patch"]
            try:
                validated_arguments = spec.input_model.model_validate(
                    action.arguments
                )
                arguments = ApplyPatchArguments.model_validate(
                    validated_arguments.model_dump()
                )
            except ValidationError as exc:
                raise _ToolFailure(
                    "invalid_arguments",
                    "apply_patch arguments do not satisfy the Tool Spec",
                ) from exc
            if (
                arguments.target_path != patch.target_path
                or arguments.unified_diff != patch.unified_diff
            ):
                raise _ToolFailure(
                    "invalid_arguments",
                    "apply_patch arguments must equal the candidate patch",
                )
            arguments = arguments.model_copy(update={"unified_diff": unified_diff})
            target_path = self._authorized_write_path(arguments.target_path)
            self._validate_single_file_patch(arguments.unified_diff, target_path)
            command = self.registered_test_command
            if command is None:
                raise _ToolFailure(
                    "invalid_arguments",
                    "Public Validation requires the registered test command",
                )
            if not command.static_check_argv:
                raise _ToolFailure(
                    "invalid_arguments",
                    "Public Validation requires a registered static check command",
                )

            with tempfile.TemporaryDirectory(prefix="coderca-validation-") as directory:
                execution_workspace = Path(directory) / "workspace"
                self._materialize_execution_workspace(execution_workspace)
                self._apply_unified_diff(
                    execution_workspace,
                    arguments.unified_diff,
                )
                static_completed = self._run_validation_container(
                    execution_workspace,
                    argv=command.static_check_argv,
                    timeout_seconds=10,
                    label="static check",
                )
                static_ref = self._write_validation_output(
                    root,
                    "static-check.txt",
                    static_completed.stdout or "",
                )
                static_check = ValidationCheckResult(
                    name="static_check",
                    passed=static_completed.returncode == 0,
                    exit_code=static_completed.returncode,
                    artifact_ref=static_ref,
                )

                test_completed = self._run_validation_container(
                    execution_workspace,
                    argv=command.argv,
                    timeout_seconds=float(command.timeout_seconds),
                    label="registered test",
                )
                test_ref = self._write_validation_output(
                    root,
                    "registered-test.txt",
                    self._format_test_artifact(
                        command,
                        exit_code=test_completed.returncode,
                        output=test_completed.stdout or "",
                    ),
                )
                registered_test = ValidationCheckResult(
                    name="registered_test",
                    passed=test_completed.returncode == 0,
                    exit_code=test_completed.returncode,
                    artifact_ref=test_ref,
                )
                if not self._is_registered_test_outcome(command, test_completed):
                    failure_category = "execution_failed"
                    failure_message = (
                        "registered test command did not produce a recognized outcome"
                    )
        except _ToolFailure as exc:
            failure_category = exc.category
            failure_message = str(exc)

        passed = (
            failure_category is None
            and static_check is not None
            and static_check.passed
            and registered_test is not None
            and registered_test.passed
        )
        if not passed and failure_message is None:
            failed_checks = [
                item.name
                for item in (static_check, registered_test)
                if item is not None and not item.passed
            ]
            failure_message = (
                "Public Validation checks failed: " + ", ".join(failed_checks)
            )
        result = PublicValidationResult(
            hypothesis_id=patch.hypothesis_id,
            status="passed" if passed else "failed",
            patch_artifact_ref=patch_ref,
            artifact_ref=validation_ref,
            static_check=static_check,
            registered_test=registered_test,
            failure_category=failure_category,
            failure_message=failure_message,
        )
        validation_path.write_text(
            json.dumps(result.model_dump(mode="json"), sort_keys=True, indent=2)
            + "\n",
            encoding="utf-8",
        )
        output = json.dumps(result.model_dump(mode="json"), sort_keys=True)
        bounded_output = output[:_DEFAULT_RESULT_LIMIT]
        tool_result = ToolResult(
            tool_result_id=tool_result_id,
            validation_action_id=action.validation_action_id,
            hypothesis_id=action.hypothesis_id,
            tool_name="apply_patch",
            status="success" if failure_category is None else "error",
            output=bounded_output,
            artifact_ref=validation_ref,
            truncated=len(output) > len(bounded_output),
            duration_ms=max(int((monotonic() - started) * 1_000), 0),
            error_category=failure_category,
            error_message=failure_message if failure_category is not None else None,
        )
        return tool_result, result

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
            validated = spec.input_model.model_validate(arguments)
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
        if isinstance(validated, RunTestsArguments):
            command = self.registered_test_command
            if command is None or validated.test_command_id != command.command_id:
                raise DecisionValidationError(
                    "run_tests requires the registered Task Manifest command ID",
                    [
                        {
                            "loc": ["arguments", "test_command_id"],
                            "type": "unknown_registered_command",
                            "msg": "Test command ID is not registered for this task.",
                            "input": validated.test_command_id,
                            "allowed_command_ids": (
                                [command.command_id] if command is not None else []
                            ),
                        }
                    ],
                )

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
        artifact_output: str | None = None
        command_id: str | None = None
        exit_code: int | None = None
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
            if spec.handler is None:
                raise _ToolFailure(
                    "invalid_arguments",
                    f"{spec.name} requires its dedicated execution boundary",
                )
            handler_result = spec.handler(arguments, spec.timeout_seconds)
            if isinstance(handler_result, _ToolExecutionOutput):
                output = handler_result.content
                artifact_output = handler_result.artifact_content
                command_id = handler_result.command_id
                exit_code = handler_result.exit_code
            else:
                output = handler_result
        except _ToolFailure as exc:
            error_category = exc.category
            error_message = str(exc)
            output = exc.artifact_output
            command_id = exc.command_id
            exit_code = exc.exit_code
        except subprocess.TimeoutExpired:
            error_category = "timeout"
            error_message = "tool execution exceeded its timeout"
        except TimeoutError:
            error_category = "timeout"
            error_message = "tool execution exceeded its timeout"
        except Exception as exc:
            error_category = "execution_failed"
            error_message = f"tool execution failed: {type(exc).__name__}"

        full_artifact = artifact_output if artifact_output is not None else output
        if error_category is not None and not full_artifact:
            full_artifact = error_message or ""
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
            truncated=len(full_artifact) > len(bounded_output),
            duration_ms=max(int((monotonic() - started) * 1_000), 0),
            error_category=error_category,
            error_message=error_message,
            command_id=command_id,
            exit_code=exit_code,
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

    def _search_code(
        self, raw: BaseModel, timeout_seconds: float
    ) -> _ToolExecutionOutput:
        arguments = SearchCodeInput.model_validate(raw.model_dump())
        deadline = monotonic() + timeout_seconds
        scopes = self._search_scopes(arguments.path)
        self._check_search_deadline(deadline)
        files = self._searchable_files(scopes, deadline=deadline)
        if arguments.search_kind == "content":
            matches, truncated = self._search_content(
                arguments,
                files,
                max(deadline - monotonic(), 0.001),
            )
        else:
            matches, truncated = self._search_paths(
                arguments, files, deadline=deadline
            )
        self._check_search_deadline(deadline)
        result = SearchCodeResult(
            query=arguments.query,
            search_kind=arguments.search_kind,
            path=arguments.path,
            status="matched" if matches else "no_matches",
            matches=tuple(matches),
            truncated=truncated,
        )
        full_output = self._serialize_search_result(result)
        if len(full_output) <= _DEFAULT_RESULT_LIMIT:
            return _ToolExecutionOutput(content=full_output)

        bounded_matches: list[SearchMatch] = []
        for match in result.matches:
            candidate = result.model_copy(
                update={
                    "matches": tuple([*bounded_matches, match]),
                    "truncated": True,
                }
            )
            serialized = self._serialize_search_result(candidate)
            if len(serialized) > _DEFAULT_RESULT_LIMIT:
                break
            bounded_matches.append(match)
        bounded_result = result.model_copy(
            update={"matches": tuple(bounded_matches), "truncated": True}
        )
        return _ToolExecutionOutput(
            content=self._serialize_search_result(bounded_result),
            artifact_content=full_output,
        )

    @staticmethod
    def _serialize_search_result(result: SearchCodeResult) -> str:
        return json.dumps(result.model_dump(mode="json"), sort_keys=True)

    def _search_content(
        self,
        arguments: SearchCodeInput,
        files: list[str],
        timeout_seconds: float,
    ) -> tuple[list[SearchMatch], bool]:
        if not files:
            return [], False
        deadline = monotonic() + timeout_seconds
        discovered: list[tuple[str, int]] = []
        for relative_path in files:
            self._check_search_deadline(deadline)
            remaining = arguments.max_results + 1 - len(discovered)
            command = [
                "rg",
                "--no-config",
                "--json",
                "--fixed-strings",
                "--line-number",
                "--max-count",
                str(remaining),
                "--max-columns",
                str(_MAX_SEARCH_SNIPPET_LENGTH),
                "--",
                arguments.query,
                relative_path,
            ]
            completed = subprocess.run(
                command,
                cwd=self.workspace_root,
                check=False,
                capture_output=True,
                text=True,
                timeout=max(deadline - monotonic(), 0.001),
            )
            if completed.returncode == 1:
                continue
            if completed.returncode != 0:
                raise _ToolFailure(
                    "execution_failed",
                    "ripgrep content search failed",
                    artifact_output=completed.stderr,
                )
            try:
                for line in completed.stdout.splitlines():
                    event = json.loads(line)
                    if event.get("type") != "match":
                        continue
                    data = event["data"]
                    path = data["path"].get("text")
                    line_number = data.get("line_number")
                    if isinstance(path, str) and isinstance(line_number, int):
                        discovered.append((Path(path).as_posix(), line_number))
            except (KeyError, TypeError, json.JSONDecodeError) as exc:
                raise _ToolFailure(
                    "execution_failed", "ripgrep returned an invalid result stream"
                ) from exc
            if len(discovered) > arguments.max_results:
                break

        truncated = len(discovered) > arguments.max_results
        matches = [
            self._content_search_match(
                path,
                line_number,
                context_lines=arguments.context_lines,
            )
            for path, line_number in discovered[: arguments.max_results]
        ]
        return matches, truncated or any(match.truncated for match in matches)

    def _search_paths(
        self,
        arguments: SearchCodeInput,
        files: list[str],
        *,
        deadline: float,
    ) -> tuple[list[SearchMatch], bool]:
        matching_paths: list[str] = []
        for path in files:
            self._check_search_deadline(deadline)
            if arguments.query in path:
                matching_paths.append(path)
        truncated = len(matching_paths) > arguments.max_results
        matches: list[SearchMatch] = []
        for path in matching_paths[: arguments.max_results]:
            matches.append(
                SearchMatch(
                    path=path,
                    snippet="",
                    truncated=False,
                )
            )
        return matches, truncated

    def _content_search_match(
        self, relative_path: str, line_number: int, *, context_lines: int
    ) -> SearchMatch:
        path = self._safe_search_file(relative_path)
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError) as exc:
            raise _ToolFailure(
                "execution_failed", "matched repository file is not readable text"
            ) from exc
        start_line = max(line_number - context_lines, 1)
        end_line = min(line_number + context_lines, max(len(lines), 1))
        selected = lines[start_line - 1 : end_line]
        snippet = "".join(
            f"{number}: {line}\n"
            for number, line in enumerate(selected, start_line)
        )
        bounded = snippet[:_MAX_SEARCH_SNIPPET_LENGTH]
        return SearchMatch(
            path=relative_path,
            start_line=start_line,
            end_line=end_line,
            snippet=bounded,
            truncated=len(snippet) > len(bounded),
        )

    def _search_scopes(self, requested_path: str | None) -> list[str]:
        raw_scopes = (
            [requested_path] if requested_path is not None else self.manifest.read_paths
        )
        scopes: list[str] = []
        for value in raw_scopes:
            normalized = self._authorized_relative_path(value)
            self._reject_answer_material(normalized)
            unresolved = self.workspace_root / normalized
            current = self.workspace_root
            for part in Path(normalized).parts:
                current /= part
                if current.is_symlink():
                    raise _ToolFailure(
                        "permission_denied", "symbolic links are not searchable"
                    )
            resolved = unresolved.resolve()
            try:
                resolved.relative_to(self.workspace_root)
            except ValueError as exc:
                raise _ToolFailure(
                    "permission_denied", "search path escapes the repository workspace"
                ) from exc
            if not resolved.exists():
                raise _ToolFailure(
                    "permission_denied", "search path is not present in the workspace"
                )
            scopes.append(normalized)
        return scopes

    def _searchable_files(
        self, scopes: list[str], *, deadline: float
    ) -> list[str]:
        if self._enforce_faulty_commit:
            return self._tracked_searchable_files(scopes, deadline=deadline)
        files: set[str] = set()
        for scope in scopes:
            self._check_search_deadline(deadline)
            path = self.workspace_root / scope
            if path.is_file():
                relative = path.relative_to(self.workspace_root).as_posix()
                if not self._is_answer_material(relative) and not path.is_symlink():
                    files.add(relative)
                continue
            for root, directories, names in os.walk(path, followlinks=False):
                self._check_search_deadline(deadline)
                root_path = Path(root)
                directories[:] = sorted(
                    directory
                    for directory in directories
                    if not (root_path / directory).is_symlink()
                    and not self._is_answer_material(
                        (root_path / directory)
                        .relative_to(self.workspace_root)
                        .as_posix()
                    )
                )
                for name in sorted(names):
                    self._check_search_deadline(deadline)
                    candidate = root_path / name
                    relative = candidate.relative_to(self.workspace_root).as_posix()
                    if candidate.is_symlink() or self._is_answer_material(relative):
                        continue
                    if candidate.is_file():
                        files.add(relative)
        return sorted(files)

    def _tracked_searchable_files(
        self, scopes: list[str], *, deadline: float
    ) -> list[str]:
        self._check_search_deadline(deadline)
        timeout_seconds = max(deadline - monotonic(), 0.001)
        try:
            head = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self.workspace_root,
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
            if head.stdout.strip() != self.manifest.faulty_commit:
                raise _ToolFailure(
                    "permission_denied",
                    "workspace is no longer at the Faulty Commit",
                )
            status = subprocess.run(
                ["git", "status", "--porcelain", "--untracked-files=no"],
                cwd=self.workspace_root,
                check=True,
                capture_output=True,
                text=True,
                timeout=max(deadline - monotonic(), 0.001),
            )
            if status.stdout:
                raise _ToolFailure(
                    "permission_denied",
                    "Faulty Commit workspace contains tracked modifications",
                )
            tracked = subprocess.run(
                ["git", "ls-files", "-z", "--", *scopes],
                cwd=self.workspace_root,
                check=True,
                capture_output=True,
                text=True,
                timeout=max(deadline - monotonic(), 0.001),
            )
        except _ToolFailure:
            raise
        except subprocess.TimeoutExpired:
            raise
        except (OSError, subprocess.SubprocessError) as exc:
            raise _ToolFailure(
                "execution_failed",
                "could not enumerate the Faulty Commit search files",
            ) from exc

        files: list[str] = []
        for value in tracked.stdout.split("\0"):
            if not value:
                continue
            self._check_search_deadline(deadline)
            normalized = Path(value).as_posix()
            if self._is_answer_material(normalized):
                continue
            path = self.workspace_root / normalized
            if path.is_symlink() or not path.is_file():
                continue
            self._authorized_relative_path(normalized)
            files.append(normalized)
        return sorted(files)

    @staticmethod
    def _check_search_deadline(deadline: float) -> None:
        if monotonic() >= deadline:
            raise TimeoutError("search_code exceeded its timeout")

    def _safe_search_file(self, relative_path: str) -> Path:
        normalized = self._authorized_relative_path(relative_path)
        self._reject_answer_material(normalized)
        path = self.workspace_root / normalized
        current = self.workspace_root
        for part in Path(normalized).parts:
            current /= part
            if current.is_symlink():
                raise _ToolFailure(
                    "permission_denied", "symbolic links are not searchable"
                )
        if not path.is_file():
            raise _ToolFailure(
                "permission_denied", "matched path is not a repository file"
            )
        return path

    def _reject_answer_material(self, relative_path: str) -> None:
        if self._is_answer_material(relative_path):
            raise _ToolFailure(
                "permission_denied", "answer and reference material is not searchable"
            )

    @staticmethod
    def _is_answer_material(relative_path: str) -> bool:
        for part in Path(relative_path).parts:
            lowered = part.casefold()
            stem = Path(lowered).stem
            if (
                lowered in {"reference.patch", "reference.diff"}
                or stem in _SEARCH_ANSWER_NAMES
            ):
                return True
        return False

    def _run_tests(
        self, raw: BaseModel, timeout_seconds: float
    ) -> _ToolExecutionOutput:
        arguments = RunTestsArguments.model_validate(raw.model_dump())
        command = self.registered_test_command
        if command is None or arguments.test_command_id != command.command_id:
            raise _ToolFailure(
                "invalid_arguments",
                "test command ID is not registered for this Diagnosis Task",
            )

        container_name = f"coderca-{uuid4().hex}"
        with tempfile.TemporaryDirectory(prefix="coderca-test-") as directory:
            execution_workspace = Path(directory) / "workspace"
            self._materialize_execution_workspace(execution_workspace)
            docker_command = [
                "docker",
                "run",
                "--rm",
                "--name",
                container_name,
                "--network",
                "none",
                "--workdir",
                "/workspace",
                "--mount",
                (
                    f"type=bind,src={execution_workspace},"
                    "dst=/workspace"
                ),
                self.manifest.docker_image,
                *command.argv,
            ]
            try:
                completed = subprocess.run(
                    docker_command,
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=timeout_seconds,
                )
            except subprocess.TimeoutExpired as exc:
                cleanup_error = self._force_remove_container(container_name)
                partial = exc.output or ""
                if isinstance(partial, bytes):
                    partial = partial.decode("utf-8", errors="replace")
                artifact = self._format_test_artifact(
                    command,
                    exit_code=None,
                    output=partial,
                )
                category: ToolErrorCategory = (
                    "timeout" if cleanup_error is None else "execution_failed"
                )
                message = (
                    "registered test command exceeded its timeout"
                    if cleanup_error is None
                    else (
                        "registered test command timed out, but container "
                        f"termination could not be confirmed: {cleanup_error}"
                    )
                )
                raise _ToolFailure(
                    category,
                    message,
                    artifact_output=artifact,
                    command_id=command.command_id,
                ) from exc

        artifact = self._format_test_artifact(
            command,
            exit_code=completed.returncode,
            output=completed.stdout or "",
        )
        is_test_outcome = self._is_registered_test_outcome(command, completed)
        if not is_test_outcome:
            raise _ToolFailure(
                "execution_failed",
                (
                    "registered test command could not produce a test outcome; "
                    "exit code or required failure marker is not registered"
                ),
                artifact_output=artifact,
                command_id=command.command_id,
                exit_code=completed.returncode,
            )
        return _ToolExecutionOutput(
            content=artifact,
            command_id=command.command_id,
            exit_code=completed.returncode,
        )

    @staticmethod
    def _is_registered_test_outcome(
        command: RegisteredTestCommand,
        completed: subprocess.CompletedProcess[str],
    ) -> bool:
        output = completed.stdout or ""
        marker_matches = not command.test_failure_output_markers or any(
            marker in output for marker in command.test_failure_output_markers
        )
        return completed.returncode == 0 or (
            completed.returncode in command.test_failure_exit_codes
            and marker_matches
        )

    def _run_validation_container(
        self,
        execution_workspace: Path,
        *,
        argv: tuple[str, ...],
        timeout_seconds: float,
        label: str,
    ) -> subprocess.CompletedProcess[str]:
        container_name = f"coderca-{uuid4().hex}"
        docker_command = [
            "docker",
            "run",
            "--rm",
            "--name",
            container_name,
            "--network",
            "none",
            "--workdir",
            "/workspace",
            "--mount",
            f"type=bind,src={execution_workspace},dst=/workspace",
            self.manifest.docker_image,
            *argv,
        ]
        try:
            return subprocess.run(
                docker_command,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=timeout_seconds,
            )
        except OSError as exc:
            raise _ToolFailure(
                "execution_failed", f"{label} could not start"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            cleanup_error = self._force_remove_container(container_name)
            if cleanup_error is None:
                raise _ToolFailure(
                    "timeout", f"{label} exceeded its timeout"
                ) from exc
            raise _ToolFailure(
                "execution_failed",
                f"{label} timed out and container cleanup failed: {cleanup_error}",
            ) from exc

    @staticmethod
    def _write_validation_output(root: Path, name: str, content: str) -> str:
        path = root / "validation" / name
        path.write_text(content, encoding="utf-8")
        return path.relative_to(root).as_posix()

    @staticmethod
    def _apply_unified_diff(workspace: Path, unified_diff: str) -> None:
        for check_only in (True, False):
            command = ["git", "apply", "--no-index"]
            if check_only:
                command.append("--check")
            command.append("-")
            try:
                completed = subprocess.run(
                    command,
                    cwd=workspace,
                    input=unified_diff,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise _ToolFailure(
                    "execution_failed", "could not invoke the patch applicator"
                ) from exc
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or "").strip()
                raise _ToolFailure(
                    "invalid_arguments",
                    "candidate patch is not applicable"
                    + (f": {detail}" if detail else ""),
                )

    def _authorized_write_path(self, value: str) -> str:
        candidate = Path(value)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise _ToolFailure(
                "permission_denied", "patch path escapes the repository workspace"
            )
        normalized = candidate.as_posix()
        if not normalized or normalized == ".":
            raise _ToolFailure("permission_denied", "patch path is empty")
        parts = {part.casefold() for part in candidate.parts}
        name = candidate.name.casefold()
        prohibited_parts = {
            "test",
            "tests",
            "benchmark",
            "benchmarks",
            "evaluation",
            "eval",
        }
        prohibited_names = {
            "manifest.json",
            "ground-truth.json",
            "registered-command.json",
            "poetry.lock",
            "uv.lock",
            "pipfile.lock",
            "pyproject.toml",
            "package-lock.json",
            "yarn.lock",
        }
        if (
            parts & prohibited_parts
            or name in prohibited_names
            or name.startswith("test_")
            or name.endswith("_test.py")
            or name.startswith("requirements")
        ):
            raise _ToolFailure(
                "permission_denied",
                "patch modifies tests, task data, Evaluation data, or dependencies",
            )
        if not any(
            normalized == allowed.rstrip("/")
            or normalized.startswith(f"{allowed.rstrip('/')}/")
            for allowed in self.manifest.write_paths
        ):
            raise _ToolFailure(
                "permission_denied", "patch path is outside Manifest write_paths"
            )
        return normalized

    @staticmethod
    def _validate_single_file_patch(unified_diff: str, target_path: str) -> None:
        lines = unified_diff.splitlines()
        prohibited_prefixes = (
            "new file mode ",
            "deleted file mode ",
            "old mode ",
            "new mode ",
            "rename from ",
            "rename to ",
            "copy from ",
            "copy to ",
            "GIT binary patch",
            "Binary files ",
        )
        if any(line.startswith(prohibited_prefixes) for line in lines):
            raise _ToolFailure(
                "permission_denied", "patch contains a prohibited modification type"
            )
        old_headers = [line[4:] for line in lines if line.startswith("--- ")]
        new_headers = [line[4:] for line in lines if line.startswith("+++ ")]
        expected_old = f"a/{target_path}"
        expected_new = f"b/{target_path}"
        if old_headers != [expected_old] or new_headers != [expected_new]:
            raise _ToolFailure(
                "permission_denied",
                "patch must modify exactly its declared target path",
            )
        if not any(line.startswith("@@ ") for line in lines):
            raise _ToolFailure(
                "invalid_arguments", "patch does not contain a unified diff hunk"
            )

    @staticmethod
    def _format_test_artifact(
        command: RegisteredTestCommand, *, exit_code: int | None, output: str
    ) -> str:
        return (
            f"command_id: {command.command_id}\n"
            f"argv: {json.dumps(list(command.argv))}\n"
            f"exit_code: {exit_code if exit_code is not None else 'timeout'}\n"
            "output:\n"
            f"{output}"
        )

    def _materialize_execution_workspace(self, destination: Path) -> None:
        if not self._enforce_faulty_commit:
            # Explicit test seam. Production CLI construction always enforces the
            # Manifest Faulty Commit and therefore uses the tracked-only path.
            shutil.copytree(self.workspace_root, destination, symlinks=True)
            return

        try:
            self._verify_faulty_commit()
            status = subprocess.run(
                ["git", "status", "--porcelain", "--untracked-files=no"],
                cwd=self.workspace_root,
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if status.stdout:
                raise _ToolFailure(
                    "permission_denied",
                    "Faulty Commit workspace contains tracked modifications",
                )
            tracked = subprocess.run(
                ["git", "ls-files", "-z"],
                cwd=self.workspace_root,
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except _ToolFailure:
            raise
        except (OSError, subprocess.SubprocessError) as exc:
            raise _ToolFailure(
                "execution_failed",
                "could not materialize the registered Faulty Commit workspace",
            ) from exc

        destination.mkdir(parents=True)
        for value in tracked.stdout.split("\0"):
            if not value:
                continue
            relative = Path(value)
            if relative.is_absolute() or ".." in relative.parts:
                raise _ToolFailure(
                    "permission_denied",
                    "Git tracked path escapes the repository workspace",
                )
            source = self.workspace_root / relative
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.is_symlink():
                target.symlink_to(source.readlink())
            elif source.is_file():
                shutil.copy2(source, target)
            else:
                raise _ToolFailure(
                    "execution_failed",
                    f"Git tracked path is not a materializable file: {value}",
                )

    @staticmethod
    def _force_remove_container(container_name: str) -> str | None:
        try:
            completed = subprocess.run(
                ["docker", "rm", "--force", container_name],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return type(exc).__name__
        if completed.returncode != 0:
            return (completed.stdout or "docker rm --force failed").strip()
        return None

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
    def __init__(
        self,
        category: ToolErrorCategory,
        message: str,
        *,
        artifact_output: str = "",
        command_id: str | None = None,
        exit_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.artifact_output = artifact_output
        self.command_id = command_id
        self.exit_code = exit_code
