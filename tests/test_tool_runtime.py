from __future__ import annotations

import subprocess
import time
from dataclasses import replace
from pathlib import Path

import pytest

from coderca.benchmark import load_task_1_manifest, materialize_task_1
from coderca.contracts import Experiment, TaskManifest
from coderca.tool_runtime import ToolRuntime


def manifest() -> TaskManifest:
    return TaskManifest(
        schema_version="1",
        task_id="task-001",
        repository_id="repo-001",
        base_snapshot="base",
        faulty_commit="faulty",
        ci_log="ci/failure.log",
        test_command_id="tests",
        docker_image="image:locked",
        read_paths=["src/"],
        write_paths=[],
        tool_call_limit=8,
    )


def experiment(tool_name: str, arguments: dict[str, object]) -> Experiment:
    return Experiment(
        experiment_id="X1",
        hypothesis_id="H1",
        purpose="Try to falsify H1 using repository evidence.",
        expected_observation="The implementation preserves the input.",
        falsification_relevance="That behavior directly contradicts H1.",
        tool_name=tool_name,
        arguments=arguments,
    )


def test_read_code_uses_registered_tool_spec_and_persists_bounded_result(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    source = workspace / "src" / "module.py"
    source.parent.mkdir(parents=True)
    source.write_text("first\nsecond\nthird\n", encoding="utf-8")
    runtime = ToolRuntime(workspace, manifest(), enforce_faulty_commit=False)

    result = runtime.execute(
        experiment(
            "read_code",
            {"path": "src/module.py", "start_line": 2, "end_line": 3},
        ),
        artifact_directory=tmp_path / "run" / "tool-results",
    )

    assert set(runtime.tool_specs) == {"inspect_diff", "read_code"}
    assert runtime.tool_specs["read_code"].permission == "read_only"
    assert runtime.tool_specs["read_code"].input_schema["type"] == "object"
    assert runtime.tool_specs["read_code"].output_schema["type"] == "object"
    assert runtime.tool_specs["read_code"].error_categories == (
        "invalid_arguments",
        "permission_denied",
        "timeout",
        "execution_failed",
    )
    assert result.status == "success"
    assert result.tool_name == "read_code"
    assert result.output == "2: second\n3: third\n"
    assert result.truncated is False
    assert result.error_category is None
    assert result.artifact_ref == "tool-results/T1.txt"
    assert (tmp_path / "run" / result.artifact_ref).read_text() == result.output


def test_runtime_projects_a_deterministic_safe_tool_catalog(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "src").mkdir(parents=True)
    runtime = ToolRuntime(workspace, manifest(), enforce_faulty_commit=False)

    catalog = runtime.available_tool_catalog()

    assert [item["name"] for item in catalog] == ["inspect_diff", "read_code"]
    assert catalog[0]["input_schema"]["type"] == "object"
    assert catalog[1]["permission"] == "read_only"
    assert catalog[1]["side_effects"] == "none"
    assert "handler" not in catalog[0]


def test_runtime_validates_tool_name_and_arguments_before_execution(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "src").mkdir(parents=True)
    runtime = ToolRuntime(workspace, manifest(), enforce_faulty_commit=False)

    with pytest.raises(ValueError, match="not registered") as unknown:
        runtime.validate_selection("run_test_with_instrumentation", {})
    with pytest.raises(ValueError, match="arguments") as invalid:
        runtime.validate_selection(
            "read_code",
            {"path": "src/module.py", "start_line": 0, "end_line": 1},
        )

    assert getattr(unknown.value, "validation_errors")[0]["loc"] == ["tool_name"]
    assert getattr(invalid.value, "validation_errors")[0]["loc"][0] == "arguments"


def test_inspect_diff_reads_only_the_frozen_base_to_faulty_change(
    tmp_path: Path,
) -> None:
    workspace = materialize_task_1(tmp_path / "workspace")
    runtime = ToolRuntime(workspace, load_task_1_manifest())

    result = runtime.execute(
        experiment("inspect_diff", {"path": "waffle/models.py"}),
        artifact_directory=tmp_path / "run" / "tool-results",
    )

    assert result.status == "success"
    assert "if self.everyone is not None" in result.output
    assert "if self.everyone:" in result.output
    assert "ground_truth" not in result.output
    assert (tmp_path / "run" / result.artifact_ref).read_text() == result.output


def test_runtime_rejects_a_workspace_not_at_the_faulty_commit(tmp_path: Path) -> None:
    workspace = materialize_task_1(tmp_path / "workspace", snapshot="base")

    with pytest.raises(ValueError, match="Faulty Commit"):
        ToolRuntime(workspace, load_task_1_manifest())


@pytest.mark.parametrize(
    ("tool_name", "arguments", "category"),
    [
        (
            "read_code",
            {"path": "../secret", "start_line": 1, "end_line": 2},
            "permission_denied",
        ),
        (
            "read_code",
            {"path": "tests/test.py", "start_line": 1, "end_line": 2},
            "permission_denied",
        ),
        (
            "read_code",
            {"path": "src/module.py", "start_line": 0, "end_line": 2},
            "invalid_arguments",
        ),
        ("unknown", {}, "invalid_arguments"),
    ],
)
def test_tool_runtime_classifies_invalid_and_denied_calls_without_retry(
    tmp_path: Path,
    tool_name: str,
    arguments: dict[str, object],
    category: str,
) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "src").mkdir(parents=True)
    (workspace / "src" / "module.py").write_text("value = 1\n")
    runtime = ToolRuntime(workspace, manifest(), enforce_faulty_commit=False)

    result = runtime.execute(
        experiment(tool_name, arguments),
        artifact_directory=tmp_path / "run" / "tool-results",
    )

    assert result.status == "error"
    assert result.error_category == category
    assert result.output == ""
    assert result.tool_result_id == "T1"
    assert len(list((tmp_path / "run" / "tool-results").iterdir())) == 1


def test_read_code_rejects_a_symlink_escape(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "src").mkdir(parents=True)
    outside = tmp_path / "outside.py"
    outside.write_text("secret = True\n")
    (workspace / "src" / "linked.py").symlink_to(outside)
    runtime = ToolRuntime(workspace, manifest(), enforce_faulty_commit=False)

    result = runtime.execute(
        experiment(
            "read_code",
            {"path": "src/linked.py", "start_line": 1, "end_line": 1},
        ),
        artifact_directory=tmp_path / "run" / "tool-results",
    )

    assert result.status == "error"
    assert result.error_category == "permission_denied"


def test_read_code_rejects_an_in_repository_symlink_outside_read_paths(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "src").mkdir(parents=True)
    (workspace / "private").mkdir()
    (workspace / "private" / "secret.py").write_text("secret = True\n")
    (workspace / "src" / "linked.py").symlink_to(
        workspace / "private" / "secret.py"
    )
    runtime = ToolRuntime(workspace, manifest(), enforce_faulty_commit=False)

    result = runtime.execute(
        experiment(
            "read_code",
            {"path": "src/linked.py", "start_line": 1, "end_line": 1},
        ),
        artifact_directory=tmp_path / "run" / "tool-results",
    )

    assert result.status == "error"
    assert result.error_category == "permission_denied"


def test_read_code_bounds_context_but_preserves_full_artifact(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    source = workspace / "src" / "module.py"
    source.parent.mkdir(parents=True)
    source.write_text("".join(f"line-{index}-{'x' * 100}\n" for index in range(200)))
    runtime = ToolRuntime(workspace, manifest(), enforce_faulty_commit=False)

    result = runtime.execute(
        experiment(
            "read_code",
            {"path": "src/module.py", "start_line": 1, "end_line": 200},
        ),
        artifact_directory=tmp_path / "run" / "tool-results",
    )

    full_artifact = (tmp_path / "run" / result.artifact_ref).read_text()
    assert result.status == "success"
    assert result.truncated is True
    assert len(result.output) == 12_000
    assert len(full_artifact) > len(result.output)


def test_inspect_diff_classifies_timeout_and_execution_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = ToolRuntime(workspace, manifest(), enforce_faulty_commit=False)

    failed = runtime.execute(
        experiment("inspect_diff", {}),
        artifact_directory=tmp_path / "failed" / "tool-results",
    )

    def timeout(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd="git", timeout=1)

    monkeypatch.setattr("coderca.tool_runtime.subprocess.run", timeout)
    timed_out = runtime.execute(
        experiment("inspect_diff", {}),
        artifact_directory=tmp_path / "timeout" / "tool-results",
    )

    assert failed.error_category == "execution_failed"
    assert timed_out.error_category == "timeout"


def test_read_code_enforces_its_registered_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    source = workspace / "src" / "module.py"
    source.parent.mkdir(parents=True)
    source.write_text("value = 1\n")
    runtime = ToolRuntime(workspace, manifest(), enforce_faulty_commit=False)
    runtime.tool_specs["read_code"] = replace(
        runtime.tool_specs["read_code"], timeout_seconds=0.01
    )

    def slow_read(path: Path) -> str:
        time.sleep(0.05)
        return path.read_text(encoding="utf-8")

    monkeypatch.setattr(runtime, "_read_file_text", slow_read, raising=False)

    result = runtime.execute(
        experiment(
            "read_code",
            {"path": "src/module.py", "start_line": 1, "end_line": 1},
        ),
        artifact_directory=tmp_path / "run" / "tool-results",
    )

    assert result.status == "error"
    assert result.error_category == "timeout"
