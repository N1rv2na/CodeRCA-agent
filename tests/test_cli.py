from __future__ import annotations

import json
from pathlib import Path

from pydantic import SecretStr

from coderca.benchmark import materialize_task_1
from coderca.cli import main
from coderca.model_provider import (
    FakeModelProvider,
    ModelConfiguration,
    StructuredOutputMode,
)


def write_manifest_with_ci_log(
    root: Path, valid_manifest_data: dict[str, object]
) -> Path:
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(valid_manifest_data), encoding="utf-8")
    ci_path = root / str(valid_manifest_data["ci_log"])
    ci_path.parent.mkdir(parents=True, exist_ok=True)
    ci_path.write_text("pytest failed: expected 1, got 2\n", encoding="utf-8")
    return manifest_path


def test_cli_success_prints_hypothesis_stage_and_run_directory(
    tmp_path: Path, valid_manifest_data: dict[str, object], capsys: object
) -> None:
    manifest_path = write_manifest_with_ci_log(tmp_path, valid_manifest_data)
    runs_dir = tmp_path / "runs"

    exit_code = main([str(manifest_path), "--runs-dir", str(runs_dir)])

    assert exit_code == 0
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert captured.err == ""
    summary = json.loads(captured.out)
    assert summary["stage"] == "diagnosing"
    assert summary["status"] == "in_progress"
    assert summary["stop_reason"] is None
    assert summary["hypothesis_history"][0]["hypothesis_id"] == "H1"
    assert summary["active_hypothesis"]["hypothesis_id"] == "H1"
    assert summary["run_id"]
    assert summary["task_id"] == "task-001"
    assert Path(summary["run_directory"]).is_dir()


def test_cli_schema_failure_is_observable_and_returns_nonzero(
    tmp_path: Path, valid_manifest_data: dict[str, object], capsys: object
) -> None:
    manifest_path = write_manifest_with_ci_log(tmp_path, valid_manifest_data)
    runs_dir = tmp_path / "runs"
    provider = FakeModelProvider(
        structured_response_sequences={
            "form_hypothesis": [{"hypothesis": {}}, {"hypothesis": {}}]
        }
    )

    exit_code = main(
        [str(manifest_path), "--runs-dir", str(runs_dir)], provider=provider
    )

    assert exit_code == 1
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert captured.err == ""
    summary = json.loads(captured.out)
    assert summary["stage"] == "finalizing"
    assert summary["status"] == "failed"
    assert summary["stop_reason"] == "schema_failure"
    assert summary["hypothesis_history"] == []
    assert summary["active_hypothesis"] is None
    assert Path(summary["run_directory"]).is_dir()


def test_cli_invalid_manifest_returns_structured_error_without_run_directory(
    tmp_path: Path, capsys: object
) -> None:
    manifest_path = tmp_path / "invalid.json"
    manifest_path.write_text('{"schema_version":"1"}', encoding="utf-8")
    runs_dir = tmp_path / "runs"

    exit_code = main([str(manifest_path), "--runs-dir", str(runs_dir)])

    assert exit_code == 2
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert captured.out == ""
    error = json.loads(captured.err)
    assert set(error) == {"error"}
    assert error["error"]["code"] == "invalid_manifest"
    assert error["error"]["message"]
    assert isinstance(error["error"]["details"], list)
    assert not runs_dir.exists()


def test_cli_explicit_configured_provider_runs_formation_path_without_network(
    tmp_path: Path, valid_manifest_data: dict[str, object], capsys: object
) -> None:
    manifest_path = write_manifest_with_ci_log(tmp_path, valid_manifest_data)
    captured_configuration: dict[str, ModelConfiguration | SecretStr] = {}

    def provider_factory(
        configuration: ModelConfiguration, api_key: SecretStr
    ) -> FakeModelProvider:
        captured_configuration["configuration"] = configuration
        captured_configuration["api_key"] = api_key
        return FakeModelProvider()

    exit_code = main(
        [
            str(manifest_path),
            "--runs-dir",
            str(tmp_path / "runs"),
            "--model-provider",
            "openai-compatible",
        ],
        environment={
            "CODERCA_MODEL_BASE_URL": "https://models.example/v1",
            "CODERCA_MODEL_ID": "example-model",
            "CODERCA_MODEL_API_KEY": "secret-key",
            "CODERCA_MODEL_STRUCTURED_OUTPUT_MODE": "json_text",
        },
        provider_factory=provider_factory,
    )

    assert exit_code == 0
    configuration = captured_configuration["configuration"]
    api_key = captured_configuration["api_key"]
    assert isinstance(configuration, ModelConfiguration)
    assert isinstance(api_key, SecretStr)
    assert configuration.structured_output_mode is (StructuredOutputMode.JSON_TEXT)
    assert api_key.get_secret_value() == "secret-key"
    assert capsys.readouterr().err == ""  # type: ignore[attr-defined]


def test_cli_workspace_runs_the_read_only_diagnosis_loop(
    tmp_path: Path, valid_manifest_data: dict[str, object], capsys: object
) -> None:
    del valid_manifest_data
    manifest_path = Path("benchmarks/django-waffle/task-1/manifest.json")
    workspace = materialize_task_1(tmp_path / "workspace")
    provider = FakeModelProvider(
        {
            "form_hypothesis": {
                "hypothesis": {
                    "root_symbol": "AbstractBaseFlag.is_active_for_user",
                    "location_description": None,
                    "mechanism": "A fallback discards explicit zero.",
                    "falsification_criterion": "The code preserves explicit zero.",
                }
            },
            "select_experiment": {
                "hypothesis_id": "H1",
                "purpose": "Inspect the Faulty Commit diff.",
                "expected_observation": "The boolean condition changed.",
                "falsification_relevance": "No condition change falsifies H1.",
                "tool_name": "inspect_diff",
                "arguments": {"path": "waffle/models.py"},
            },
            "update_evidence": {
                "hypothesis_id": "H1",
                "observation_ref": "O1",
                "direction": "supporting",
                "explanation": "The observed branch matches the claimed location.",
            },
            "assess_hypothesis": {
                "outcome": "sufficiently_supported",
                "evidence_refs": ["E1"],
                "rationale": "The code Evidence is sufficient for read-only RCA.",
            },
        }
    )

    exit_code = main(
        [
            str(manifest_path),
            "--runs-dir",
            str(tmp_path / "runs"),
            "--workspace",
            str(workspace),
        ],
        provider=provider,
    )

    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert summary["status"] == "completed"
    assert summary["stop_reason"] == "read_only_diagnosis_complete"
    assert summary["active_hypothesis"] is None
    assert summary["evidence_refs"] == ["E1"]
    select_request = next(
        item
        for item in provider.structured_requests
        if item["schema_name"] == "select_experiment"
    )
    select_context = json.loads(select_request["user_prompt"])
    assert [item["name"] for item in select_context["available_tools"]] == [
        "inspect_diff",
        "read_code",
        "run_tests",
    ]


def test_cli_workspace_rejects_the_default_formation_only_fake_provider(
    tmp_path: Path,
    valid_manifest_data: dict[str, object],
    capsys: object,
) -> None:
    manifest_path = write_manifest_with_ci_log(tmp_path, valid_manifest_data)

    exit_code = main([str(manifest_path), "--workspace", str(tmp_path)])

    assert exit_code == 2
    error = json.loads(capsys.readouterr().err)  # type: ignore[attr-defined]
    assert error["error"]["code"] == "model_provider_required"
