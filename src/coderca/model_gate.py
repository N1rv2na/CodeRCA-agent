"""Explicit advisory compatibility checks for a Model Configuration."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Literal, Protocol, TypeVar
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, model_validator

from .contracts import ContractModel, NonEmptyString
from .model_provider import (
    ModelConfiguration,
    ModelFailureCategory,
    ModelProviderError,
    StructuredModelResponse,
)


class PreflightProbe(ContractModel):
    status: Literal["ok"]
    model_id: NonEmptyString


class StageSchemaProbe(ContractModel):
    stage: Literal["hypothesis_generation"]
    next_action: Literal["inspect_code"]
    reason: NonEmptyString


class ReadCodeArguments(ContractModel):
    path: NonEmptyString
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_range_and_path(self) -> ReadCodeArguments:
        path = Path(self.path)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("read_code path must stay within the repository")
        if self.end_line < self.start_line:
            raise ValueError("end_line must not precede start_line")
        return self


class ToolArgumentsProbe(ContractModel):
    hypothesis_id: Literal["H1"]
    purpose: NonEmptyString
    expected_observation: NonEmptyString
    tool_name: Literal["read_code"]
    arguments: ReadCodeArguments


class EvidenceUpdateProbe(ContractModel):
    hypothesis_id: Literal["H1"]
    observation_ref: NonEmptyString
    direction: Literal["contradicting"]
    evidence_summary: NonEmptyString
    rationale: NonEmptyString


class PythonPatchProbe(ContractModel):
    hypothesis_id: Literal["H1"]
    target_path: Literal["sample.py"]
    mechanism: NonEmptyString
    unified_diff: NonEmptyString


class GateRequestConfiguration(ContractModel):
    stream: Literal[False] = False
    temperature: Literal[0] = 0
    response_format_type: Literal["json_schema"] = "json_schema"
    strict: Literal[True] = True


class ProbeResult(ContractModel):
    name: NonEmptyString
    status: Literal["passed", "failed"]
    failure_category: ModelFailureCategory | None = None
    original_response_artifact: NonEmptyString | None = None


class ModelCompatibilityReport(ContractModel):
    schema_version: Literal["1"] = "1"
    endpoint: NonEmptyString
    model_id: NonEmptyString
    request_configuration: GateRequestConfiguration
    compatible: bool
    failure_category: ModelFailureCategory | None = None
    probes: list[ProbeResult] = Field(min_length=1, max_length=5)


ProbeModel = TypeVar("ProbeModel", bound=BaseModel)


class StructuredModelProvider(Protocol):
    def generate_structured(
        self,
        *,
        schema_name: str,
        system_prompt: str,
        user_prompt: str,
        response_model: type[ProbeModel],
    ) -> StructuredModelResponse[ProbeModel]:
        """Generate one locally validated structured probe response."""


class ProbeDefinition(ContractModel):
    name: NonEmptyString
    system_prompt: NonEmptyString
    user_prompt: NonEmptyString


_SYSTEM_PROMPT = (
    "Return only the requested structured object. Do not use Markdown or add fields."
)
_PATCH_SOURCE = (
    "def select_timeout(configured: int | None, default: int) -> int:\n"
    "    return configured or default\n"
)
_NO_RETURN = object()


def run_model_compatibility_gate(
    *,
    provider: StructuredModelProvider,
    configuration: ModelConfiguration,
    output_directory: Path,
) -> ModelCompatibilityReport:
    """Run at most five advisory probes and persist a redacted report."""

    output_directory = Path(output_directory)
    response_directory = output_directory / "responses"
    response_directory.mkdir(parents=True, exist_ok=True)
    results: list[ProbeResult] = []

    probes: tuple[tuple[ProbeDefinition, type[BaseModel]], ...] = (
        (
            ProbeDefinition(
                name="preflight",
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=(
                    "Confirm this configured model can return a strict structured "
                    "response. Return status 'ok' and model_id "
                    f"'{configuration.model_id}'."
                ),
            ),
            PreflightProbe,
        ),
        (
            ProbeDefinition(
                name="stage_schema",
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=(
                    "A CI test failed. Select hypothesis_generation as the stage "
                    "and inspect_code as the next action, with a short reason."
                ),
            ),
            StageSchemaProbe,
        ),
        (
            ProbeDefinition(
                name="tool_arguments",
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=(
                    "For Hypothesis H1 about incorrect explicit False handling, "
                    "request read_code for waffle/models.py lines 1 through 150. "
                    "Include a purpose and expected observation."
                ),
            ),
            ToolArgumentsProbe,
        ),
        (
            ProbeDefinition(
                name="evidence_update",
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=(
                    "Hypothesis H1 claims explicit False is ignored by a truthiness "
                    "guard. Observation obs-read-code-001 shows `if override is not "
                    "None`. Record contradicting Evidence with a summary and rationale."
                ),
            ),
            EvidenceUpdateProbe,
        ),
        (
            ProbeDefinition(
                name="python_patch",
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=(
                    "For Hypothesis H1, generate a unified diff for sample.py that "
                    "changes this function so configured=0 is preserved:\n"
                    f"{_PATCH_SOURCE}"
                ),
            ),
            PythonPatchProbe,
        ),
    )

    failure_category: ModelFailureCategory | None = None
    for definition, response_model in probes:
        structured_response: StructuredModelResponse[BaseModel] | None = None
        try:
            structured_response = provider.generate_structured(
                schema_name=definition.name,
                system_prompt=definition.system_prompt,
                user_prompt=definition.user_prompt,
                response_model=response_model,
            )
            response = structured_response.value
            if definition.name == "preflight":
                _validate_preflight(response, configuration.model_id)
            elif definition.name == "python_patch":
                _validate_python_patch(response)
            artifact = _write_original_response_artifact(
                response_directory,
                definition.name,
                structured_response.raw_response,
            )
            results.append(
                ProbeResult(
                    name=definition.name,
                    status="passed",
                    original_response_artifact=str(
                        artifact.relative_to(output_directory)
                    ),
                )
            )
        except ModelProviderError as exc:
            failure_category = exc.category
            artifact_reference: str | None = None
            original_response = exc.original_response
            if original_response is None and structured_response is not None:
                original_response = structured_response.raw_response
            if original_response is not None:
                artifact = _write_original_response_artifact(
                    response_directory,
                    definition.name,
                    original_response,
                )
                artifact_reference = str(
                    artifact.relative_to(output_directory)
                )
            results.append(
                ProbeResult(
                    name=definition.name,
                    status="failed",
                    failure_category=exc.category,
                    original_response_artifact=artifact_reference,
                )
            )
            break

    report = ModelCompatibilityReport(
        endpoint=_redacted_endpoint(configuration.base_url),
        model_id=configuration.model_id,
        request_configuration=GateRequestConfiguration(),
        compatible=failure_category is None and len(results) == len(probes),
        failure_category=failure_category,
        probes=results,
    )
    output_directory.mkdir(parents=True, exist_ok=True)
    (output_directory / "model-gate.json").write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def _validate_preflight(response: BaseModel, expected_model_id: str) -> None:
    if (
        not isinstance(response, PreflightProbe)
        or response.model_id != expected_model_id
    ):
        raise ModelProviderError(
            "model_mismatch", "Preflight returned a different model identifier."
        )


def _validate_python_patch(response: BaseModel) -> None:
    if not isinstance(response, PythonPatchProbe):
        raise ModelProviderError(
            "schema_mismatch", "The patch probe returned the wrong contract."
        )
    try:
        patched = _apply_single_hunk(_PATCH_SOURCE, response.unified_diff)
        tree = ast.parse(patched, filename=response.target_path)
        _validate_patch_behavior(tree)
    except (SyntaxError, ValueError) as exc:
        raise ModelProviderError(
            "patch_not_applicable", "The probe patch is not applicable Python."
        ) from exc


def _validate_patch_behavior(tree: ast.Module) -> None:
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
        raise ValueError("patch must contain exactly one function")
    function = tree.body[0]
    if (
        function.name != "select_timeout"
        or [argument.arg for argument in function.args.args]
        != ["configured", "default"]
        or function.decorator_list
    ):
        raise ValueError("patch changed the probe function boundary")
    for configured, default, expected in ((0, 30, 0), (None, 30, 30), (10, 30, 10)):
        actual = _evaluate_statements(
            function.body, {"configured": configured, "default": default}
        )
        if actual is _NO_RETURN or actual != expected:
            raise ValueError("patch does not preserve required behavior")


def _evaluate_statements(
    statements: list[ast.stmt], environment: dict[str, int | None]
) -> object:
    for statement in statements:
        if isinstance(statement, ast.Return):
            if statement.value is None:
                return None
            return _evaluate_expression(statement.value, environment)
        if isinstance(statement, ast.If):
            branch = statement.body if _evaluate_expression(
                statement.test, environment
            ) else statement.orelse
            result = _evaluate_statements(branch, environment)
            if result is not _NO_RETURN:
                return result
            continue
        raise ValueError("patch contains unsupported statements")
    return _NO_RETURN


def _evaluate_expression(
    expression: ast.expr, environment: dict[str, int | None]
) -> int | None | bool:
    if isinstance(expression, ast.Name) and expression.id in environment:
        return environment[expression.id]
    if isinstance(expression, ast.Constant) and expression.value is None:
        return None
    if isinstance(expression, ast.IfExp):
        branch = expression.body if _evaluate_expression(
            expression.test, environment
        ) else expression.orelse
        return _evaluate_expression(branch, environment)
    if (
        isinstance(expression, ast.Compare)
        and len(expression.ops) == 1
        and len(expression.comparators) == 1
        and isinstance(expression.ops[0], (ast.Is, ast.IsNot))
    ):
        left = _evaluate_expression(expression.left, environment)
        right = _evaluate_expression(expression.comparators[0], environment)
        if isinstance(expression.ops[0], ast.Is):
            return left is right
        return left is not right
    raise ValueError("patch contains unsupported expressions")


def _apply_single_hunk(source: str, unified_diff: str) -> str:
    lines = unified_diff.splitlines()
    if len(lines) < 4 or lines[0] != "--- a/sample.py" or lines[1] != "+++ b/sample.py":
        raise ValueError("patch headers do not target sample.py")
    match = re.fullmatch(r"@@ -(\d+),(\d+) \+(\d+),(\d+) @@", lines[2])
    if match is None or int(match.group(1)) != int(match.group(3)):
        raise ValueError("unsupported patch hunk")

    source_lines = source.splitlines()
    source_index = int(match.group(1)) - 1
    output = source_lines[:source_index]
    removed = 0
    added = 0
    for line in lines[3:]:
        if not line or line[0] not in " +-":
            raise ValueError("invalid patch line")
        marker, content = line[0], line[1:]
        if marker in " -":
            if (
                source_index >= len(source_lines)
                or source_lines[source_index] != content
            ):
                raise ValueError("patch context does not apply")
            source_index += 1
            removed += 1
        if marker in " +":
            output.append(content)
            added += 1
    if removed != int(match.group(2)) or added != int(match.group(4)):
        raise ValueError("patch hunk counts do not match")
    output.extend(source_lines[source_index:])
    return "\n".join(output) + "\n"


def _write_original_response_artifact(
    directory: Path, probe_name: str, response: object
) -> Path:
    path = directory / f"{probe_name}.json"
    path.write_text(
        json.dumps(response, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _redacted_endpoint(base_url: str) -> str:
    parsed = urlsplit(base_url)
    return f"{parsed.scheme}://{parsed.netloc}"
