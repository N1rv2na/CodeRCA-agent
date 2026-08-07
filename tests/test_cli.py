from __future__ import annotations

import json
from pathlib import Path

from coderca.cli import main


def test_cli_success_prints_terminal_summary_and_run_directory(
    tmp_path: Path, valid_manifest_data: dict[str, object], capsys: object
) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(valid_manifest_data), encoding="utf-8")
    runs_dir = tmp_path / "runs"

    exit_code = main([str(manifest_path), "--runs-dir", str(runs_dir)])

    assert exit_code == 0
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert captured.err == ""
    summary = json.loads(captured.out)
    assert summary["stage"] == "finalizing"
    assert summary["status"] == "completed"
    assert summary["stop_reason"] == "fake_model_completed"
    assert summary["run_id"]
    assert summary["task_id"] == "task-001"
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
