from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import replace
from pathlib import Path

import pytest

from coderca.benchmark import load_task_1_manifest, materialize_task_1
from coderca.contracts import Experiment, RegisteredTestCommand, TaskManifest
from coderca.tool_runtime import ToolRuntime, load_registered_test_command

TASK_1_DIRECTORY = Path("benchmarks/django-waffle/task-1")


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


def registered_command(
    *, timeout_seconds: int = 30, argv: tuple[str, ...] | None = None
) -> RegisteredTestCommand:
    return RegisteredTestCommand(
        schema_version="1",
        command_id="tests",
        argv=argv or ("python", "-m", "pytest", "-q"),
        timeout_seconds=timeout_seconds,
    )


def test_registered_test_command_loader_accepts_fixed_argv_and_expected_id(
    tmp_path: Path,
) -> None:
    path = tmp_path / "registered-command.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "command_id": "tests",
                "argv": ["python", "-m", "pytest", "-q"],
                "timeout_seconds": 30,
            }
        )
    )

    command = load_registered_test_command(path, expected_command_id="tests")

    assert isinstance(command, RegisteredTestCommand)
    assert command.argv == ("python", "-m", "pytest", "-q")
    assert command.timeout_seconds == 30


def test_registered_test_command_loader_rejects_shell_or_unexpected_id(
    tmp_path: Path,
) -> None:
    shell_path = tmp_path / "shell-command.json"
    shell_path.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "command_id": "tests",
                "command": "pytest -q; curl https://example.test",
                "timeout_seconds": 30,
            }
        )
    )
    valid_path = tmp_path / "registered-command.json"
    valid_path.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "command_id": "other-tests",
                "argv": ["python", "-m", "pytest", "-q"],
                "timeout_seconds": 30,
            }
        )
    )

    with pytest.raises(ValueError, match="contract"):
        load_registered_test_command(shell_path, expected_command_id="tests")
    with pytest.raises(ValueError, match="does not match"):
        load_registered_test_command(valid_path, expected_command_id="tests")


def test_run_tests_uses_isolated_networkless_workspace_and_preserves_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    source = workspace / "src" / "module.py"
    source.parent.mkdir(parents=True)
    source.write_text("value = 1\n")
    runtime = ToolRuntime(
        workspace,
        manifest(),
        registered_test_command=registered_command(),
        enforce_faulty_commit=False,
    )
    run_tests_spec = runtime.tool_specs["run_tests"]
    assert run_tests_spec.permission == "code_execution"
    assert run_tests_spec.side_effects == "temporary_workspace"
    assert run_tests_spec.timeout_seconds == 30
    assert [item["name"] for item in runtime.available_tool_catalog()] == [
        "inspect_diff",
        "read_code",
        "run_tests",
    ]
    docker_commands: list[list[str]] = []
    mounted_workspaces: list[Path] = []

    def completed(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        del kwargs
        docker_commands.append(command)
        mount = command[command.index("--mount") + 1]
        source_value = next(
            item.removeprefix("src=")
            for item in mount.split(",")
            if item.startswith("src=")
        )
        mounted_workspace = Path(source_value)
        mounted_workspaces.append(mounted_workspace)
        assert mounted_workspace.is_dir()
        assert (mounted_workspace / "src" / "module.py").read_text() == "value = 1\n"
        (mounted_workspace / "container-created.txt").write_text("temporary\n")
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="FAILED test_case\n" + ("x" * 13_000),
        )

    monkeypatch.setenv("CODERCA_MODEL_API_KEY", "must-not-enter-container")
    monkeypatch.setenv("CODERCA_MODEL_BASE_URL", "https://models.example/v1")
    monkeypatch.setattr("coderca.tool_runtime.subprocess.run", completed)

    first = runtime.execute(
        experiment("run_tests", {"test_command_id": "tests"}),
        artifact_directory=tmp_path / "run" / "tool-results",
    )
    second = runtime.execute(
        experiment("run_tests", {"test_command_id": "tests"}),
        artifact_directory=tmp_path / "run" / "tool-results",
    )

    assert [item[0:2] for item in docker_commands] == [
        ["docker", "run"],
        ["docker", "run"],
    ]
    assert all("--network" in item and "none" in item for item in docker_commands)
    assert all("--workdir" in item and "/workspace" in item for item in docker_commands)
    assert all("--env" not in item and "-e" not in item for item in docker_commands)
    assert all("must-not-enter-container" not in item for item in docker_commands)
    assert all("https://models.example/v1" not in item for item in docker_commands)
    assert all(
        item[-4:] == ["python", "-m", "pytest", "-q"]
        for item in docker_commands
    )
    assert len(set(mounted_workspaces)) == 2
    assert all(not item.exists() for item in mounted_workspaces)
    assert not (workspace / "container-created.txt").exists()
    assert first.status == "success"
    assert first.command_id == "tests"
    assert first.exit_code == 1
    assert first.truncated is True
    assert len(first.output) == 12_000
    artifact = (tmp_path / "run" / first.artifact_ref).read_text()
    assert 'argv: ["python", "-m", "pytest", "-q"]' in artifact
    assert "exit_code: 1" in artifact
    assert len(artifact) > len(first.output)
    assert second.tool_result_id == "T2"


def test_run_tests_passing_exit_is_a_successful_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "src").mkdir(parents=True)
    runtime = ToolRuntime(
        workspace,
        manifest(),
        registered_test_command=registered_command(),
        enforce_faulty_commit=False,
    )

    def passed(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        del kwargs
        return subprocess.CompletedProcess(command, 0, stdout="1 passed\n")

    monkeypatch.setattr("coderca.tool_runtime.subprocess.run", passed)

    result = runtime.execute(
        experiment("run_tests", {"test_command_id": "tests"}),
        artifact_directory=tmp_path / "run" / "tool-results",
    )

    assert result.status == "success"
    assert result.exit_code == 0
    assert "1 passed" in result.output


@pytest.mark.parametrize(
    "arguments",
    [
        {"test_command_id": "unknown"},
        {"test_command_id": "tests", "command": "pytest; curl example.test"},
        {"test_command_id": "tests", "path": "../outside"},
    ],
)
def test_run_tests_rejects_unregistered_or_model_controlled_execution_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    arguments: dict[str, object],
) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "src").mkdir(parents=True)
    runtime = ToolRuntime(
        workspace,
        manifest(),
        registered_test_command=registered_command(),
        enforce_faulty_commit=False,
    )
    calls = 0

    def forbidden(*args: object, **kwargs: object) -> None:
        del args, kwargs
        nonlocal calls
        calls += 1
        raise AssertionError("Docker must not start for rejected arguments")

    monkeypatch.setattr("coderca.tool_runtime.subprocess.run", forbidden)

    with pytest.raises(ValueError):
        runtime.validate_selection("run_tests", arguments)
    result = runtime.execute(
        experiment("run_tests", arguments),
        artifact_directory=tmp_path / "run" / "tool-results",
    )

    assert result.status == "error"
    assert result.error_category == "invalid_arguments"
    assert calls == 0


def test_run_tests_timeout_force_removes_container_without_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "src").mkdir(parents=True)
    runtime = ToolRuntime(
        workspace,
        manifest(),
        registered_test_command=registered_command(timeout_seconds=1),
        enforce_faulty_commit=False,
    )
    calls: list[list[str]] = []

    def timeout_then_cleanup(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        del kwargs
        calls.append(command)
        if command[1] == "run":
            raise subprocess.TimeoutExpired(command, timeout=1, output="partial\n")
        return subprocess.CompletedProcess(command, 0, stdout="")

    monkeypatch.setattr(
        "coderca.tool_runtime.subprocess.run", timeout_then_cleanup
    )

    result = runtime.execute(
        experiment("run_tests", {"test_command_id": "tests"}),
        artifact_directory=tmp_path / "run" / "tool-results",
    )

    assert result.status == "error"
    assert result.error_category == "timeout"
    assert len(calls) == 2
    assert calls[1][0:3] == ["docker", "rm", "--force"]


def test_run_tests_classifies_docker_execution_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "src").mkdir(parents=True)
    runtime = ToolRuntime(
        workspace,
        manifest(),
        registered_test_command=registered_command(),
        enforce_faulty_commit=False,
    )

    def failed(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        del kwargs
        return subprocess.CompletedProcess(command, 125, stdout="daemon unavailable\n")

    monkeypatch.setattr("coderca.tool_runtime.subprocess.run", failed)

    result = runtime.execute(
        experiment("run_tests", {"test_command_id": "tests"}),
        artifact_directory=tmp_path / "run" / "tool-results",
    )

    assert result.status == "error"
    assert result.error_category == "execution_failed"
    assert result.exit_code == 125
    assert "daemon unavailable" in (
        tmp_path / "run" / result.artifact_ref
    ).read_text()


def test_run_tests_classifies_unregistered_nonzero_exit_as_execution_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "src").mkdir(parents=True)
    runtime = ToolRuntime(
        workspace,
        manifest(),
        registered_test_command=registered_command(),
        enforce_faulty_commit=False,
    )

    def collection_error(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        del kwargs
        return subprocess.CompletedProcess(
            command,
            2,
            stdout="ERROR: test collection failed\n",
        )

    monkeypatch.setattr("coderca.tool_runtime.subprocess.run", collection_error)

    result = runtime.execute(
        experiment("run_tests", {"test_command_id": "tests"}),
        artifact_directory=tmp_path / "run" / "tool-results",
    )

    assert result.status == "error"
    assert result.error_category == "execution_failed"
    assert result.exit_code == 2


def test_run_tests_reports_cleanup_failure_instead_of_claiming_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "src").mkdir(parents=True)
    runtime = ToolRuntime(
        workspace,
        manifest(),
        registered_test_command=registered_command(timeout_seconds=1),
        enforce_faulty_commit=False,
    )

    def timeout_then_failed_cleanup(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        del kwargs
        if command[1] == "run":
            raise subprocess.TimeoutExpired(command, timeout=1, output="partial\n")
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="cannot remove running container\n",
        )

    monkeypatch.setattr(
        "coderca.tool_runtime.subprocess.run", timeout_then_failed_cleanup
    )

    result = runtime.execute(
        experiment("run_tests", {"test_command_id": "tests"}),
        artifact_directory=tmp_path / "run" / "tool-results",
    )

    assert result.status == "error"
    assert result.error_category == "execution_failed"
    assert "termination could not be confirmed" in (result.error_message or "")


def test_run_tests_materializes_only_clean_tracked_faulty_commit_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = materialize_task_1(tmp_path / "workspace")
    (workspace / ".env").write_text("CODERCA_MODEL_API_KEY=secret\n")
    manifest_value = load_task_1_manifest()
    command = load_registered_test_command(
        TASK_1_DIRECTORY / "registered-command.json",
        expected_command_id=manifest_value.test_command_id,
    )
    runtime = ToolRuntime(
        workspace,
        manifest_value,
        registered_test_command=command,
    )
    real_run = subprocess.run

    def inspect_materialized_workspace(
        docker_command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        del kwargs
        if docker_command[0] == "git":
            return real_run(
                docker_command,
                cwd=workspace,
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
        mount = docker_command[docker_command.index("--mount") + 1]
        source_value = next(
            item.removeprefix("src=")
            for item in mount.split(",")
            if item.startswith("src=")
        )
        mounted_workspace = Path(source_value)
        assert (mounted_workspace / "waffle" / "models.py").is_file()
        assert not (mounted_workspace / ".env").exists()
        assert not (mounted_workspace / ".git").exists()
        return subprocess.CompletedProcess(
            docker_command,
            1,
            stdout="expected failure\n",
        )

    monkeypatch.setattr(
        "coderca.tool_runtime.subprocess.run", inspect_materialized_workspace
    )

    result = runtime.execute(
        experiment(
            "run_tests",
            {"test_command_id": manifest_value.test_command_id},
        ),
        artifact_directory=tmp_path / "run" / "tool-results",
    )

    assert result.status == "success"
    assert result.exit_code == 1


def test_run_tests_rejects_tracked_workspace_changes_before_docker_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = materialize_task_1(tmp_path / "workspace")
    manifest_value = load_task_1_manifest()
    command = load_registered_test_command(
        TASK_1_DIRECTORY / "registered-command.json",
        expected_command_id=manifest_value.test_command_id,
    )
    runtime = ToolRuntime(
        workspace,
        manifest_value,
        registered_test_command=command,
    )
    with (workspace / "waffle" / "models.py").open("a") as source:
        source.write("\n# dirty workspace must not enter Docker\n")
    docker_started = False
    real_run = subprocess.run

    def reject_docker(
        command_line: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        del kwargs
        nonlocal docker_started
        if command_line[0] == "git":
            return real_run(
                command_line,
                cwd=workspace,
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
        docker_started = True
        raise AssertionError("Docker must not start for a dirty Faulty Commit")

    monkeypatch.setattr("coderca.tool_runtime.subprocess.run", reject_docker)

    result = runtime.execute(
        experiment(
            "run_tests",
            {"test_command_id": manifest_value.test_command_id},
        ),
        artifact_directory=tmp_path / "run" / "tool-results",
    )

    assert result.status == "error"
    assert result.error_category == "permission_denied"
    assert docker_started is False


def test_task_1_registered_command_runs_in_real_docker_when_image_is_available(
    tmp_path: Path,
) -> None:
    manifest_value = load_task_1_manifest()
    _require_docker_image(manifest_value.docker_image)
    workspace = materialize_task_1(tmp_path / "workspace")
    command = load_registered_test_command(
        TASK_1_DIRECTORY / "registered-command.json",
        expected_command_id=manifest_value.test_command_id,
    )
    runtime = ToolRuntime(
        workspace,
        manifest_value,
        registered_test_command=command,
    )

    result = runtime.execute(
        experiment(
            "run_tests",
            {"test_command_id": manifest_value.test_command_id},
        ),
        artifact_directory=tmp_path / "run" / "tool-results",
    )

    assert result.status == "success"
    assert result.exit_code == 1
    assert "CRCA_TASK_1_EXPECTED_ASSERTION_MISMATCH" in (
        tmp_path / "run" / result.artifact_ref
    ).read_text()


def test_real_docker_boundary_has_only_loopback_and_no_model_key_when_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_value = manifest().model_copy(
        update={
            "test_command_id": "boundary-probe",
            "docker_image": load_task_1_manifest().docker_image,
        }
    )
    _require_docker_image(manifest_value.docker_image)
    workspace = tmp_path / "workspace"
    (workspace / "src").mkdir(parents=True)
    script = (
        "import os; "
        "assert sorted(os.listdir('/sys/class/net')) == ['lo']; "
        "assert 'CODERCA_MODEL_API_KEY' not in os.environ; "
        "print('BOUNDARY_OK')"
    )
    command = RegisteredTestCommand(
        schema_version="1",
        command_id="boundary-probe",
        argv=("python", "-c", script),
        timeout_seconds=10,
    )
    monkeypatch.setenv("CODERCA_MODEL_API_KEY", "must-not-enter-container")
    runtime = ToolRuntime(
        workspace,
        manifest_value,
        registered_test_command=command,
        enforce_faulty_commit=False,
    )

    result = runtime.execute(
        experiment("run_tests", {"test_command_id": "boundary-probe"}),
        artifact_directory=tmp_path / "run" / "tool-results",
    )

    assert result.status == "success"
    assert result.exit_code == 0
    assert "BOUNDARY_OK" in result.output
    assert "must-not-enter-container" not in result.output


@pytest.mark.parametrize(
    ("script", "expected_status", "expected_category", "expected_exit_code"),
    [
        ("print('PASS')", "success", None, 0),
        ("import sys; print('FAIL'); sys.exit(1)", "success", None, 1),
        (
            "import sys; print('COLLECTION_ERROR'); sys.exit(2)",
            "error",
            "execution_failed",
            2,
        ),
    ],
)
def test_real_docker_classifies_registered_test_outcomes_when_available(
    tmp_path: Path,
    script: str,
    expected_status: str,
    expected_category: str | None,
    expected_exit_code: int,
) -> None:
    image = load_task_1_manifest().docker_image
    _require_docker_image(image)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    command = RegisteredTestCommand(
        schema_version="1",
        command_id="docker-outcome-probe",
        argv=("python", "-c", script),
        timeout_seconds=10,
    )
    manifest_value = manifest().model_copy(
        update={
            "test_command_id": command.command_id,
            "docker_image": image,
        }
    )
    runtime = ToolRuntime(
        workspace,
        manifest_value,
        registered_test_command=command,
        enforce_faulty_commit=False,
    )

    result = runtime.execute(
        experiment("run_tests", {"test_command_id": command.command_id}),
        artifact_directory=tmp_path / "run" / "tool-results",
    )

    assert result.status == expected_status
    assert result.error_category == expected_category
    assert result.exit_code == expected_exit_code


def test_real_docker_timeout_terminates_named_container_when_available(
    tmp_path: Path,
) -> None:
    image = load_task_1_manifest().docker_image
    _require_docker_image(image)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    command = RegisteredTestCommand(
        schema_version="1",
        command_id="docker-timeout-probe",
        argv=("python", "-c", "import time; time.sleep(30)"),
        timeout_seconds=1,
    )
    manifest_value = manifest().model_copy(
        update={
            "test_command_id": command.command_id,
            "docker_image": image,
        }
    )
    runtime = ToolRuntime(
        workspace,
        manifest_value,
        registered_test_command=command,
        enforce_faulty_commit=False,
    )

    result = runtime.execute(
        experiment("run_tests", {"test_command_id": command.command_id}),
        artifact_directory=tmp_path / "run" / "tool-results",
    )

    assert result.status == "error"
    assert result.error_category == "timeout"


def _require_docker_image(image: str) -> None:
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker executable is not installed")
    inspected = subprocess.run(
        [docker, "image", "inspect", image],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if inspected.returncode != 0:
        pytest.skip(f"frozen Docker image is not available: {image}")


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
