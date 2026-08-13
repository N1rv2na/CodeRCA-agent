from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from coderca.model_gate import (
    PROBE_NAMES,
    GateResult,
    GeminiCompatibilityGate,
    check_probe_output,
)
from coderca.model_gate_cli import main as gate_main
from coderca.model_provider import (
    GeminiErrorCategory,
    GeminiProviderError,
    ProviderResponse,
)


def probe_output(name: str) -> dict[str, Any]:
    if name == "stage_schema":
        return {
            "stage": "hypothesis_generation",
            "next_action": "inspect_code",
            "reason": "Inspect the changed symbol before forming an experiment.",
        }
    if name == "tool_arguments":
        return {
            "hypothesis_id": "H1",
            "purpose": "Inspect the public model implementation.",
            "expected_observation": "The target function source is returned.",
            "tool_name": "read_code",
            "arguments": {"path": "waffle/models.py", "start_line": 1, "end_line": 150},
        }
    if name == "contradicting_evidence":
        return {
            "hypothesis_id": "H1",
            "observation_ref": "obs-read-code-001",
            "direction": "contradicting",
            "evidence_summary": "The observation does not match the hypothesis.",
            "rationale": "The observed branch rules out the proposed mechanism.",
        }
    if name == "python_patch":
        return {
            "hypothesis_id": "H1",
            "target_path": "sample.py",
            "mechanism": "Correct the public fixture's branch.",
            "unified_diff": (
                "--- a/sample.py\n+++ b/sample.py\n@@ -1,2 +1,2 @@\n"
                " def select_timeout(configured: int | None, default: int) -> int:\n"
                "-    return configured or default\n"
                "+    return configured if configured is not None else default\n"
            ),
        }
    raise AssertionError(name)


@dataclass
class StubProvider:
    outputs: dict[str, dict[str, Any]]
    fail_preflight: bool = False

    def __post_init__(self) -> None:
        self.calls: list[str] = []
        self.preflight_calls = 0

    def preflight(self) -> ProviderResponse:
        self.preflight_calls += 1
        if self.fail_preflight:
            raise GeminiProviderError(
                GeminiErrorCategory.AUTHENTICATION, "authentication failed"
            )
        return ProviderResponse({}, {"id": "preflight"}, {}, {})

    def complete_probe(self, prompt: str, **kwargs: Any) -> ProviderResponse:
        name = next(name for name in PROBE_NAMES if name in prompt)
        assert kwargs["response_schema"] == _expected_schema_shape(name)
        self.calls.append(name)
        content = self.outputs[name]
        return ProviderResponse(
            content,
            {"id": f"{name}-{len(self.calls)}", "content": content},
            {"role": "assistant", "content": json.dumps(content)},
            {},
        )


def _expected_schema_shape(name: str) -> dict[str, Any]:
    from coderca.model_gate import _PROBE_SCHEMAS

    return _PROBE_SCHEMAS[name]


def test_gate_runs_each_probe_exactly_three_times_and_persists_redacted_results(
    tmp_path: Path,
) -> None:
    provider = StubProvider({name: probe_output(name) for name in PROBE_NAMES})

    result = GeminiCompatibilityGate(provider).run(tmp_path)

    assert isinstance(result, GateResult)
    assert result.compatible is True
    assert provider.preflight_calls == 1
    assert provider.calls == [name for name in PROBE_NAMES for _ in range(3)]
    manifest = json.loads((tmp_path / "model-gate.json").read_text())
    assert manifest["compatible"] is True
    assert manifest["model"] == "gemini-3.6-flash"
    assert len(manifest["raw_response_references"]) == 12
    assert all(
        (tmp_path / ref).is_file() for ref in manifest["raw_response_references"]
    )


def test_gate_short_circuits_probes_when_preflight_fails(tmp_path: Path) -> None:
    provider = StubProvider({}, fail_preflight=True)

    result = GeminiCompatibilityGate(provider).run(tmp_path)

    assert result.compatible is False
    assert result.failure_category == GeminiErrorCategory.AUTHENTICATION.value
    assert provider.calls == []
    assert json.loads((tmp_path / "model-gate.json").read_text())["probes"] == []


@pytest.mark.parametrize(
        "name, bad_output",
    [
        (
            "tool_arguments",
            {
                **probe_output("tool_arguments"),
                "tool_name": "unknown",
            },
        ),
        (
            "python_patch",
            {
                **probe_output("python_patch"),
                "unified_diff": "not a patch",
            },
        ),
    ],
)
def test_gate_rejects_invalid_probe_contracts(
    tmp_path: Path, name: str, bad_output: dict[str, Any]
) -> None:
    outputs = {probe: probe_output(probe) for probe in PROBE_NAMES}
    outputs[name] = bad_output

    result = GeminiCompatibilityGate(StubProvider(outputs)).run(tmp_path)

    assert result.compatible is False
    assert any(
        outcome["probe"] == name and not outcome["valid"]
        for outcome in result.outcomes
    )


def test_probe_check_does_not_accept_contradicting_evidence_without_source(
) -> None:
    assert not check_probe_output(
        "contradicting_evidence", {"direction": "contradicting"}
    ).valid


def test_probe_check_rejects_extra_fields() -> None:
    output = {**probe_output("stage_schema"), "unexpected": True}
    assert not check_probe_output("stage_schema", output).valid


@pytest.mark.parametrize(
    "bad_arguments",
    [
        {
            "path": "waffle/models.py",
            "start_line": 1,
            "end_line": 150,
            "shell": "echo unsafe",
        },
        {"path": "waffle/models.py", "start_line": True, "end_line": 150},
    ],
)
def test_probe_check_rejects_invalid_nested_tool_arguments(
    bad_arguments: dict[str, Any],
) -> None:
    output = {**probe_output("tool_arguments"), "arguments": bad_arguments}
    assert not check_probe_output("tool_arguments", output).valid


def test_probe_check_requires_frozen_evidence_references() -> None:
    output = {
        **probe_output("contradicting_evidence"),
        "observation_ref": "unrelated-observation",
    }
    assert not check_probe_output("contradicting_evidence", output).valid


def test_patch_check_rejects_non_applicable_hunk_location() -> None:
    output = probe_output("python_patch")
    output["unified_diff"] = str(output["unified_diff"]).replace(
        "@@ -1,2 +1,2 @@", "@@ -999,2 +999,2 @@"
    )
    assert not check_probe_output("python_patch", output).valid


def test_gate_artifacts_never_contain_api_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "sentinel-key")
    provider = StubProvider({name: probe_output(name) for name in PROBE_NAMES})
    provider.outputs["stage_schema"] = {
        **probe_output("stage_schema"),
        "note": "sentinel-key",
    }

    GeminiCompatibilityGate(provider).run(tmp_path)

    artifact_text = "".join(
        path.read_text() for path in tmp_path.rglob("*") if path.is_file()
    )
    assert "sentinel-key" not in artifact_text


def test_explicit_gate_cli_without_key_does_not_call_network(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: Any
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    exit_code = gate_main(["--output-directory", str(tmp_path)])

    assert exit_code == 3
    assert json.loads(capsys.readouterr().out)["failure_category"] == (
        "missing_credentials"
    )
