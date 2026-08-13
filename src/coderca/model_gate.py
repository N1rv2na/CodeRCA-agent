"""Explicit, auditable Gemini compatibility gate.

The gate is intentionally separate from diagnosis orchestration.  It accepts
only public fixture prompts, validates four small contracts, and never makes a
failed compatibility check look like a usable provider.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .model_provider import (
    GEMINI_API_KEY_ENV,
    GEMINI_BASE_URL,
    GEMINI_MODEL,
    GeminiErrorCategory,
    GeminiProviderError,
    ProviderResponse,
)

PROBE_NAMES = (
    "stage_schema",
    "tool_arguments",
    "contradicting_evidence",
    "python_patch",
)
PROBE_ATTEMPTS = 3
_PROBE_SCHEMAS: dict[str, dict[str, Any]] = {
    "stage_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "stage": {"type": "string", "enum": ["hypothesis_generation"]},
            "next_action": {"type": "string", "enum": ["inspect_code"]},
            "reason": {"type": "string", "minLength": 1},
        },
        "required": ["stage", "next_action", "reason"],
    },
    "tool_arguments": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "hypothesis_id": {"type": "string", "minLength": 1},
            "purpose": {"type": "string", "minLength": 1},
            "expected_observation": {"type": "string", "minLength": 1},
            "tool_name": {"type": "string", "enum": ["read_code"]},
            "arguments": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "path": {"type": "string", "enum": ["waffle/models.py"]},
                    "start_line": {"type": "integer", "minimum": 1},
                    "end_line": {"type": "integer", "minimum": 1},
                },
                "required": ["path", "start_line", "end_line"],
            },
        },
        "required": [
            "hypothesis_id",
            "purpose",
            "expected_observation",
            "tool_name",
            "arguments",
        ],
    },
    "contradicting_evidence": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "hypothesis_id": {"type": "string", "minLength": 1},
            "observation_ref": {"type": "string", "minLength": 1},
            "direction": {"type": "string", "enum": ["contradicting"]},
            "evidence_summary": {"type": "string", "minLength": 1},
            "rationale": {"type": "string", "minLength": 1},
        },
        "required": [
            "hypothesis_id",
            "observation_ref",
            "direction",
            "evidence_summary",
            "rationale",
        ],
    },
    "python_patch": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "hypothesis_id": {"type": "string", "minLength": 1},
            "target_path": {"type": "string", "enum": ["sample.py"]},
            "mechanism": {"type": "string", "minLength": 1},
            "unified_diff": {"type": "string", "minLength": 1},
        },
        "required": ["hypothesis_id", "target_path", "mechanism", "unified_diff"],
    },
}


class StructuredProbeProvider(Protocol):
    def preflight(self) -> ProviderResponse: ...

    def complete_probe(
        self,
        prompt: str,
        *,
        response_schema: dict[str, Any],
    ) -> ProviderResponse: ...

@dataclass(frozen=True)
class ProbeCheck:
    valid: bool
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class GateResult:
    compatible: bool
    model: str = GEMINI_MODEL
    failure_category: str | None = None
    outcomes: list[dict[str, Any]] = field(default_factory=list)
    artifact_manifest: Path | None = None

def check_probe_output(name: str, output: Any) -> ProbeCheck:
    """Validate one public probe response without repairing malformed output."""

    errors: list[str] = []
    if not isinstance(output, dict):
        return ProbeCheck(False, ["response must be a JSON object"])
    schema = _PROBE_SCHEMAS.get(name)
    if schema is None:
        return ProbeCheck(False, ["unknown probe"])
    expected_fields = set(schema["properties"])
    required_fields = set(schema["required"])
    extra_fields = set(output) - expected_fields
    missing_fields = required_fields - set(output)
    if extra_fields:
        errors.append(f"unexpected fields: {sorted(extra_fields)!r}")
    if missing_fields:
        errors.append(f"missing fields: {sorted(missing_fields)!r}")
    if name == "stage_schema":
        if output.get("stage") != "hypothesis_generation":
            errors.append("stage must be hypothesis_generation")
        if output.get("next_action") != "inspect_code":
            errors.append("next_action must be inspect_code")
        if not isinstance(output.get("reason"), str) or not output["reason"]:
            errors.append("reason must be a non-empty string")
    elif name == "tool_arguments":
        for field_name in ("hypothesis_id", "purpose", "expected_observation"):
            if not isinstance(output.get(field_name), str) or not output[field_name]:
                errors.append(f"{field_name} must be a non-empty string")
        if output.get("tool_name") != "read_code":
            errors.append("tool_name must be read_code")
        arguments = output.get("arguments")
        if not isinstance(arguments, dict):
            errors.append("arguments must be an object")
        else:
            expected_arguments = {"path", "start_line", "end_line"}
            extra_arguments = set(arguments) - expected_arguments
            missing_arguments = expected_arguments - set(arguments)
            if extra_arguments:
                errors.append(
                    f"unexpected argument fields: {sorted(extra_arguments)!r}"
                )
            if missing_arguments:
                errors.append(
                    f"missing argument fields: {sorted(missing_arguments)!r}"
                )
            if arguments.get("path") != "waffle/models.py":
                errors.append("arguments.path must target the public fixture")
            start_line = arguments.get("start_line")
            end_line = arguments.get("end_line")
            if type(start_line) is not int or start_line < 1:
                errors.append("arguments.start_line must be a positive integer")
            if type(end_line) is not int or end_line < 1:
                errors.append("arguments.end_line must be a positive integer")
            if type(start_line) is int and type(end_line) is int:
                if end_line < start_line or end_line - start_line > 150:
                    errors.append("arguments line range is invalid")
    elif name == "contradicting_evidence":
        if output.get("hypothesis_id") != "H1":
            errors.append("hypothesis_id must be H1")
        if output.get("observation_ref") != "obs-read-code-001":
            errors.append("observation_ref must be obs-read-code-001")
        if output.get("direction") != "contradicting":
            errors.append("direction must be contradicting")
        for field_name in (
            "hypothesis_id",
            "observation_ref",
            "evidence_summary",
            "rationale",
        ):
            if not isinstance(output.get(field_name), str) or not output[field_name]:
                errors.append(f"{field_name} must be a non-empty string")
    elif name == "python_patch":
        for field_name in ("hypothesis_id", "target_path", "mechanism"):
            if not isinstance(output.get(field_name), str) or not output[field_name]:
                errors.append(f"{field_name} must be a non-empty string")
        patch = output.get("unified_diff")
        if output.get("target_path") != "sample.py":
            errors.append("target_path must be sample.py")
        if not isinstance(patch, str) or not _is_applicable_patch(patch):
            errors.append("unified_diff must be an applicable sample.py patch")
    else:
        errors.append("unknown probe")
    return ProbeCheck(not errors, errors)


def _is_applicable_patch(patch: str) -> bool:
    """Perform a deterministic, shell-free unified-diff sanity/applicability check."""

    lines = patch.splitlines()
    if len(lines) < 4 or lines[0] != "--- a/sample.py" or lines[1] != "+++ b/sample.py":
        return False
    hunk = next((line for line in lines[2:] if line.startswith("@@ ")), "")
    if not hunk or hunk != "@@ -1,2 +1,2 @@":
        return False
    try:
        old_part, new_part = hunk.split(" ")[1:3]
        old_count = (
            int(old_part.split(",", 1)[1].split(" ")[0])
            if "," in old_part
            else 1
        )
        new_count = (
            int(new_part.split(",", 1)[1].split(" ")[0])
            if "," in new_part
            else 1
        )
    except (IndexError, ValueError):
        return False
    hunk_lines = lines[lines.index(hunk) + 1 :]
    if not hunk_lines or any(
        line.startswith("--- ") or line.startswith("+++ ") for line in hunk_lines
    ):
        return False
    old_seen = sum(1 for line in hunk_lines if line.startswith((" ", "-")))
    new_seen = sum(1 for line in hunk_lines if line.startswith((" ", "+")))
    expected_old = [
        "def select_timeout(configured: int | None, default: int) -> int:",
        "    return configured or default",
    ]
    expected_new = [
        "def select_timeout(configured: int | None, default: int) -> int:",
        "    return configured if configured is not None else default",
    ]
    actual_old = [line[1:] for line in hunk_lines if line.startswith((" ", "-"))]
    actual_new = [line[1:] for line in hunk_lines if line.startswith((" ", "+"))]
    return (
        old_seen == old_count
        and new_seen == new_count
        and any(line.startswith("-") for line in hunk_lines)
        and any(line.startswith("+") for line in hunk_lines)
        and actual_old == expected_old
        and actual_new == expected_new
        and not any("../" in line for line in lines)
    )


class GeminiCompatibilityGate:
    """Run the frozen four-probe compatibility contract."""

    def __init__(self, provider: StructuredProbeProvider) -> None:
        self.provider = provider
        # This is used solely for redaction.  It is never put in an artifact.
        self._secret = os.environ.get(GEMINI_API_KEY_ENV, "")

    def run(self, output_directory: Path) -> GateResult:
        output_directory = Path(output_directory)
        raw_directory = output_directory / "raw-responses"
        raw_directory.mkdir(parents=True, exist_ok=True)
        outcomes: list[dict[str, Any]] = []
        raw_references: list[str] = []
        failure_category: str | None = None
        try:
            self.provider.preflight()
        except GeminiProviderError as error:
            failure_category = error.category.value
            result = GateResult(
                compatible=False,
                failure_category=failure_category,
                outcomes=outcomes,
            )
            return self._persist(output_directory, result, raw_references)
        except Exception:
            failure_category = GeminiErrorCategory.NETWORK.value
            result = GateResult(
                compatible=False,
                failure_category=failure_category,
                outcomes=outcomes,
            )
            return self._persist(output_directory, result, raw_references)

        compatible = True
        for probe in PROBE_NAMES:
            for attempt in range(1, PROBE_ATTEMPTS + 1):
                reference = Path("raw-responses") / f"{probe}-{attempt}.json"
                raw_references.append(str(reference))
                try:
                    response = self.provider.complete_probe(
                        self._prompt(probe), response_schema=_PROBE_SCHEMAS[probe]
                    )
                    content = response.content
                    raw = response.raw_response
                    check = check_probe_output(probe, content)
                    if not check.valid:
                        compatible = False
                    outcomes.append(
                        {
                            "probe": probe,
                            "attempt": attempt,
                            "valid": check.valid,
                            "errors": check.errors,
                            "raw_response_reference": str(reference),
                        }
                    )
                    self._write_json(raw_directory / reference.name, self._redact(raw))
                except GeminiProviderError as error:
                    compatible = False
                    failure_category = failure_category or error.category.value
                    outcomes.append(
                        {
                            "probe": probe,
                            "attempt": attempt,
                            "valid": False,
                            "errors": ["provider request failed"],
                            "failure_category": error.category.value,
                            "raw_response_reference": str(reference),
                        }
                    )
                    self._write_json(
                        raw_directory / reference.name,
                        {"error_category": error.category.value},
                    )
                except Exception:
                    compatible = False
                    failure_category = (
                        failure_category
                        or GeminiErrorCategory.INVALID_RESPONSE.value
                    )
                    outcomes.append(
                        {
                            "probe": probe,
                            "attempt": attempt,
                            "valid": False,
                            "errors": ["provider returned an invalid response"],
                            "failure_category": failure_category,
                            "raw_response_reference": str(reference),
                        }
                    )
                    self._write_json(
                        raw_directory / reference.name,
                        {"error_category": GeminiErrorCategory.INVALID_RESPONSE.value},
                    )
        result = GateResult(
            compatible=compatible,
            failure_category=failure_category,
            outcomes=outcomes,
        )
        return self._persist(output_directory, result, raw_references)

    @staticmethod
    def _prompt(probe: str) -> str:
        return {
            "stage_schema": (
                "stage_schema: Return ONLY JSON with exactly "
                "stage='hypothesis_generation', "
                "next_action='inspect_code', and a non-empty reason."
            ),
            "tool_arguments": (
                "tool_arguments: Return ONLY JSON for hypothesis H1 using tool_name "
                "'read_code' and arguments path='waffle/models.py', start_line=1, "
                "end_line=150; include purpose and expected_observation."
            ),
            "contradicting_evidence": (
                "contradicting_evidence: Hypothesis H1 claims an explicit False is "
                "ignored by a truthiness guard. Observation obs-read-code-001 shows "
                "`if override is not None`. Return ONLY JSON with hypothesis_id H1, "
                "that observation_ref, direction='contradicting', evidence_summary, "
                "and rationale."
            ),
            "python_patch": (
                "python_patch: Return ONLY JSON with hypothesis_id H1, target_path "
                "sample.py, mechanism, and unified_diff. Public sample.py contains "
                "`return configured or default`; replace it with `return configured "
                "if configured is not None else default` so zero is preserved. The "
                "diff must begin exactly with --- a/sample.py and +++ b/sample.py."
            ),
        }[probe]

    def _persist(
        self,
        output_directory: Path,
        result: GateResult,
        raw_references: list[str],
    ) -> GateResult:
        manifest = {
            "compatible": result.compatible,
            "model": GEMINI_MODEL,
            "base_url": GEMINI_BASE_URL,
            "generation_config": {
                "temperature": 0,
                "response_format": {"type": "json_schema"},
            },
            "probe_schemas": _PROBE_SCHEMAS,
            "preflight": "passed" if result.outcomes or result.compatible else "failed",
            "failure_category": result.failure_category,
            "raw_response_references": raw_references,
            "probes": result.outcomes,
        }
        path = output_directory / "model-gate.json"
        self._write_json(path, self._redact(manifest))
        return GateResult(
            compatible=result.compatible,
            model=result.model,
            failure_category=result.failure_category,
            outcomes=result.outcomes,
            artifact_manifest=path,
        )

    def _redact(self, value: Any) -> Any:
        secret = self._secret
        if isinstance(value, str):
            if secret:
                return value.replace(secret, "[REDACTED]")
            return value
        if isinstance(value, dict):
            return {
                str(key): self._redact(item)
                for key, item in value.items()
                if str(key).lower()
                not in {"authorization", "api_key", "gemini_api_key"}
            }
        if isinstance(value, list):
            return [self._redact(item) for item in value]
        return value

    @staticmethod
    def _write_json(path: Path, value: Any) -> None:
        path.write_text(
            json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
