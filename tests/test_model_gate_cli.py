from __future__ import annotations

import json
from importlib.util import find_spec
from pathlib import Path

from coderca import model_gate, model_gate_cli
from coderca.model_provider import FakeModelProvider, ModelConfiguration


def test_model_gate_cli_module_exists() -> None:
    assert find_spec("coderca.model_gate_cli") is not None


def valid_environment() -> dict[str, str]:
    return {
        "CODERCA_MODEL_BASE_URL": "https://models.example/v1",
        "CODERCA_MODEL_ID": "example-model",
        "CODERCA_MODEL_API_KEY": "secret-key",
    }


def test_cli_runs_the_explicit_gate_and_prints_the_report_location(
    tmp_path: Path,
    capsys: object,
    valid_model_gate_responses: dict[str, dict[str, object]],
) -> None:
    output_directory = tmp_path / "gate"

    exit_code = model_gate_cli.main(
        ["--output-directory", str(output_directory)],
        environment=valid_environment(),
        provider_factory=(
            lambda configuration, api_key, timeout: FakeModelProvider(
                valid_model_gate_responses
            )
        ),
    )

    assert exit_code == 0
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert captured.err == ""
    summary = json.loads(captured.out)
    assert summary == {
        "compatible": True,
        "failure_category": None,
        "model": "example-model",
        "model_compatibility_report": str(
            output_directory / "model-gate.json"
        ),
    }


def test_cli_reports_missing_configuration_without_creating_gate_artifacts(
    tmp_path: Path, capsys: object
) -> None:
    output_directory = tmp_path / "gate"
    environment = valid_environment()
    del environment["CODERCA_MODEL_API_KEY"]

    exit_code = model_gate_cli.main(
        ["--output-directory", str(output_directory)], environment=environment
    )

    assert exit_code == 2
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert captured.out == ""
    error = json.loads(captured.err)["error"]
    assert error["code"] == "configuration_error"
    assert error["details"] == {"missing": ["CODERCA_MODEL_API_KEY"]}
    assert "secret-key" not in captured.err
    assert not output_directory.exists()


def test_cli_returns_nonzero_for_an_incompatible_report(
    tmp_path: Path,
    capsys: object,
    monkeypatch: object,
    valid_model_gate_responses: dict[str, dict[str, object]],
) -> None:
    output_directory = tmp_path / "gate"

    def incompatible_gate(
        *,
        provider: object,
        configuration: ModelConfiguration,
        output_directory: Path,
    ) -> model_gate.ModelCompatibilityReport:
        report = model_gate.ModelCompatibilityReport(
            endpoint="https://models.example",
            model_id=configuration.model_id,
            request_configuration=model_gate.GateRequestConfiguration(),
            compatible=False,
            failure_category="schema_mismatch",
            probes=[
                model_gate.ProbeResult(
                    name="preflight",
                    status="failed",
                    failure_category="schema_mismatch",
                )
            ],
        )
        output_directory.mkdir(parents=True)
        (output_directory / "model-gate.json").write_text(
            report.model_dump_json()
        )
        return report

    monkeypatch.setattr(  # type: ignore[attr-defined]
        model_gate_cli, "run_model_compatibility_gate", incompatible_gate, raising=False
    )

    exit_code = model_gate_cli.main(
        ["--output-directory", str(output_directory)],
        environment=valid_environment(),
        provider_factory=(
            lambda configuration, api_key, timeout: FakeModelProvider(
                valid_model_gate_responses
            )
        ),
    )

    assert exit_code == 1
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    summary = json.loads(captured.out)
    assert summary["compatible"] is False
    assert summary["failure_category"] == "schema_mismatch"
