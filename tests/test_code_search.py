from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, cast

import pytest

from coderca.benchmark import load_task_1_manifest, materialize_task_1
from coderca.contracts import Experiment, TaskManifest
from coderca.tool_runtime import SearchCodeResult, ToolRuntime


def manifest(*, read_paths: list[str] | None = None) -> TaskManifest:
    return TaskManifest(
        schema_version="1",
        task_id="task-search",
        repository_id="repo-search",
        base_snapshot="base",
        faulty_commit="faulty",
        ci_log="ci/failure.log",
        test_command_id="tests",
        docker_image="image:locked",
        read_paths=read_paths or ["src/"],
        write_paths=[],
        tool_call_limit=8,
    )


def search_experiment(arguments: dict[str, object]) -> Experiment:
    return Experiment(
        experiment_id="X1",
        hypothesis_id="H1",
        purpose="Find code that can falsify the Active Hypothesis.",
        expected_observation="A bounded repository match or a valid zero result.",
        falsification_relevance="The result distinguishes the proposed mechanism.",
        tool_name="search_code",
        arguments=arguments,
    )


def execute_search(
    runtime: ToolRuntime, tmp_path: Path, arguments: dict[str, object]
) -> tuple[Any, SearchCodeResult]:
    result = runtime.execute(
        search_experiment(arguments),
        artifact_directory=tmp_path / "run" / "tool-results",
    )
    payload = SearchCodeResult.model_validate_json(result.output)
    return result, payload


def test_content_search_is_literal_bounded_and_artifact_backed(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    source = workspace / "src" / "flags.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "before = 1\n"
        "def is_active(user):\n"
        "    return user.name == 'a.*b'\n"
        "after = 2\n",
        encoding="utf-8",
    )
    runtime = ToolRuntime(workspace, manifest(), enforce_faulty_commit=False)

    result, payload = execute_search(
        runtime,
        tmp_path,
        {
            "query": "  a.*b  ",
            "search_kind": "content",
            "max_results": 5,
            "context_lines": 1,
        },
    )

    assert result.status == "success"
    assert result.error_category is None
    assert result.artifact_ref == "tool-results/T1.txt"
    assert payload.query == "a.*b"
    assert payload.search_kind == "content"
    assert payload.status == "matched"
    assert payload.truncated is False
    assert len(payload.matches) == 1
    match = payload.matches[0]
    assert match.path == "src/flags.py"
    assert (match.start_line, match.end_line) == (2, 4)
    assert "3:     return user.name == 'a.*b'" in match.snippet
    assert match.truncated is False
    assert (tmp_path / "run" / result.artifact_ref).read_text() == result.output


@pytest.mark.parametrize("query", ["flags.py", "src/nested/flags", "flags"])
def test_path_search_matches_repository_relative_paths_deterministically(
    tmp_path: Path, query: str
) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "src" / "nested").mkdir(parents=True)
    (workspace / "src" / "z_flags.py").write_text("z = 1\n")
    (workspace / "src" / "nested" / "flags.py").write_text("n = 1\n")
    runtime = ToolRuntime(workspace, manifest(), enforce_faulty_commit=False)

    _, first = execute_search(
        runtime,
        tmp_path,
        {
            "query": query,
            "search_kind": "path",
            "max_results": 10,
            "context_lines": 0,
        },
    )
    _, second = execute_search(
        runtime,
        tmp_path,
        {
            "query": query,
            "search_kind": "path",
            "max_results": 10,
            "context_lines": 0,
        },
    )

    assert first.status == "matched"
    assert [match.path for match in first.matches] == sorted(
        match.path for match in first.matches
    )
    assert first.model_dump(exclude={"artifact_ref"}) == second.model_dump(
        exclude={"artifact_ref"}
    )
    assert all(match.start_line is None for match in first.matches)
    assert all(match.end_line is None for match in first.matches)


def test_legal_zero_result_is_a_successful_no_matches_result(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "src").mkdir(parents=True)
    (workspace / "src" / "module.py").write_text("value = 1\n")
    runtime = ToolRuntime(workspace, manifest(), enforce_faulty_commit=False)

    result, payload = execute_search(
        runtime,
        tmp_path,
        {"query": "missing", "search_kind": "content"},
    )

    assert result.status == "success"
    assert payload.status == "no_matches"
    assert payload.matches == ()
    assert payload.truncated is False


def test_search_scope_is_limited_to_manifest_read_paths(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "src").mkdir(parents=True)
    (workspace / "private").mkdir()
    (workspace / "src" / "allowed.py").write_text("needle = True\n")
    (workspace / "private" / "secret.py").write_text("needle = True\n")
    runtime = ToolRuntime(workspace, manifest(), enforce_faulty_commit=False)

    _, payload = execute_search(
        runtime,
        tmp_path,
        {"query": "needle", "search_kind": "content"},
    )
    denied = runtime.execute(
        search_experiment(
            {"query": "needle", "search_kind": "content", "path": "private"}
        ),
        artifact_directory=tmp_path / "denied" / "tool-results",
    )

    assert [match.path for match in payload.matches] == ["src/allowed.py"]
    assert denied.status == "error"
    assert denied.error_category == "permission_denied"


@pytest.mark.parametrize("path", ["../outside", "/tmp/outside", "src/link"])
def test_search_rejects_traversal_absolute_and_symlink_scopes(
    tmp_path: Path, path: str
) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "src").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.py").write_text("needle = True\n")
    (workspace / "src" / "link").symlink_to(outside, target_is_directory=True)
    runtime = ToolRuntime(workspace, manifest(), enforce_faulty_commit=False)

    result = runtime.execute(
        search_experiment(
            {"query": "needle", "search_kind": "content", "path": path}
        ),
        artifact_directory=tmp_path / "run" / "tool-results",
    )

    assert result.status == "error"
    assert result.error_category == "permission_denied"


def test_search_skips_symlinked_and_answer_material(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "src").mkdir(parents=True)
    outside = tmp_path / "outside.py"
    outside.write_text("needle = 'outside'\n")
    (workspace / "src" / "linked.py").symlink_to(outside)
    (workspace / "src" / "ground_truth.json").write_text('{"needle": true}\n')
    (workspace / "src" / "reference.patch").write_text("+needle\n")
    (workspace / "src" / "module.py").write_text("needle = 'allowed'\n")
    runtime = ToolRuntime(workspace, manifest(), enforce_faulty_commit=False)

    _, payload = execute_search(
        runtime,
        tmp_path,
        {"query": "needle", "search_kind": "content"},
    )

    assert [match.path for match in payload.matches] == ["src/module.py"]


@pytest.mark.parametrize(
    "arguments",
    [
        {"query": "", "search_kind": "content"},
        {"query": "x" * 201, "search_kind": "content"},
        {"query": "x", "search_kind": "regex"},
        {"query": "x", "search_kind": "content", "max_results": 0},
        {"query": "x", "search_kind": "content", "max_results": 21},
        {"query": "x", "search_kind": "content", "context_lines": 6},
        {"query": "x", "search_kind": "content", "path": ""},
        {"query": "x", "search_kind": "content", "path": "src\nprivate"},
        {"query": "x", "search_kind": "content", "unknown": True},
    ],
)
def test_search_rejects_invalid_bounded_arguments(
    tmp_path: Path, arguments: dict[str, object]
) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "src").mkdir(parents=True)
    runtime = ToolRuntime(workspace, manifest(), enforce_faulty_commit=False)

    result = runtime.execute(
        search_experiment(arguments),
        artifact_directory=tmp_path / "run" / "tool-results",
    )

    assert result.status == "error"
    assert result.error_category == "invalid_arguments"


def test_search_caps_results_and_snippets_while_preserving_full_payload(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    source = workspace / "src" / "many.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "".join(f"needle_{index} = '{'x' * 2200}'\n" for index in range(3)),
        encoding="utf-8",
    )
    runtime = ToolRuntime(workspace, manifest(), enforce_faulty_commit=False)

    result, payload = execute_search(
        runtime,
        tmp_path,
        {
            "query": "needle",
            "search_kind": "content",
            "max_results": 2,
            "context_lines": 0,
        },
    )

    assert payload.status == "matched"
    assert payload.truncated is True
    assert len(payload.matches) == 2
    assert all(match.truncated for match in payload.matches)
    assert all(len(match.snippet) <= 2_000 for match in payload.matches)
    assert (tmp_path / "run" / result.artifact_ref).read_text() == result.output


def test_search_total_output_stays_valid_json_and_full_result_is_artifact_backed(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    source = workspace / "src" / "many.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "".join(f"needle_{index} = '{'x' * 2200}'\n" for index in range(20)),
        encoding="utf-8",
    )
    runtime = ToolRuntime(workspace, manifest(), enforce_faulty_commit=False)

    result = runtime.execute(
        search_experiment(
            {
                "query": "needle",
                "search_kind": "content",
                "max_results": 20,
                "context_lines": 0,
            }
        ),
        artifact_directory=tmp_path / "run" / "tool-results",
    )

    visible = SearchCodeResult.model_validate_json(result.output)
    full = SearchCodeResult.model_validate_json(
        (tmp_path / "run" / result.artifact_ref).read_text()
    )
    assert result.status == "success"
    assert result.truncated is True
    assert visible.truncated is True
    assert len(result.output) <= 12_000
    assert len(visible.matches) < len(full.matches) == 20


def test_search_classifies_ripgrep_timeout_and_execution_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "src").mkdir(parents=True)
    (workspace / "src" / "module.py").write_text("needle = True\n")
    runtime = ToolRuntime(workspace, manifest(), enforce_faulty_commit=False)

    def timeout(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd="rg", timeout=1)

    monkeypatch.setattr("coderca.tool_runtime.subprocess.run", timeout)
    timed_out = runtime.execute(
        search_experiment({"query": "needle", "search_kind": "content"}),
        artifact_directory=tmp_path / "timeout" / "tool-results",
    )

    def failed(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        command = cast(list[str], args[0])
        return subprocess.CompletedProcess(command, 2, stdout="", stderr="rg failed")

    monkeypatch.setattr("coderca.tool_runtime.subprocess.run", failed)
    failed_result = runtime.execute(
        search_experiment({"query": "needle", "search_kind": "content"}),
        artifact_directory=tmp_path / "failed" / "tool-results",
    )

    assert timed_out.error_category == "timeout"
    assert failed_result.error_category == "execution_failed"


def test_search_tool_spec_exposes_only_the_typed_contract(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "src").mkdir(parents=True)
    runtime = ToolRuntime(workspace, manifest(), enforce_faulty_commit=False)

    spec = runtime.tool_specs["search_code"]
    schema = spec.input_schema

    assert spec.permission == "read_only"
    assert spec.side_effects == "none"
    assert spec.output_model is SearchCodeResult
    assert schema["additionalProperties"] is False
    assert set(cast(dict[str, object], schema["properties"])) == {
        "query",
        "search_kind",
        "path",
        "max_results",
        "context_lines",
    }
    assert [item["name"] for item in runtime.available_tool_catalog()] == [
        "inspect_diff",
        "read_code",
        "search_code",
    ]


def test_search_uses_the_frozen_faulty_commit_workspace(tmp_path: Path) -> None:
    workspace = materialize_task_1(tmp_path / "workspace")
    runtime = ToolRuntime(workspace, load_task_1_manifest())

    _, payload = execute_search(
        runtime,
        tmp_path,
        {
            "query": "is_active_for_user",
            "search_kind": "content",
            "path": "waffle/models.py",
            "max_results": 5,
            "context_lines": 1,
        },
    )

    assert payload.status == "matched"
    assert {match.path for match in payload.matches} == {"waffle/models.py"}
    assert any("def is_active_for_user" in match.snippet for match in payload.matches)
    assert all("ground_truth" not in match.path for match in payload.matches)


def test_search_rejects_tracked_worktree_changes_after_runtime_creation(
    tmp_path: Path,
) -> None:
    workspace = materialize_task_1(tmp_path / "workspace")
    runtime = ToolRuntime(workspace, load_task_1_manifest())
    source = workspace / "waffle" / "models.py"
    source.write_text(
        source.read_text(encoding="utf-8") + "\nCRCA_REPAIRED_ONLY_SENTINEL = True\n",
        encoding="utf-8",
    )

    result = runtime.execute(
        search_experiment(
            {
                "query": "CRCA_REPAIRED_ONLY_SENTINEL",
                "search_kind": "content",
            }
        ),
        artifact_directory=tmp_path / "run" / "tool-results",
    )

    assert result.status == "error"
    assert result.error_category == "permission_denied"


def test_search_ignores_untracked_files_even_inside_read_paths(tmp_path: Path) -> None:
    workspace = materialize_task_1(tmp_path / "workspace")
    manifest_value = load_task_1_manifest().model_copy(
        update={"read_paths": ["waffle/"]}
    )
    (workspace / "waffle" / "candidate_repair.py").write_text(
        "CRCA_UNTRACKED_REPAIR_SENTINEL = True\n",
        encoding="utf-8",
    )
    runtime = ToolRuntime(workspace, manifest_value)

    _, payload = execute_search(
        runtime,
        tmp_path,
        {
            "query": "CRCA_UNTRACKED_REPAIR_SENTINEL",
            "search_kind": "content",
        },
    )

    assert payload.status == "no_matches"


def test_content_search_disables_ripgrep_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    source = workspace / "src" / "module.py"
    source.parent.mkdir(parents=True)
    source.write_text("needle = True\n", encoding="utf-8")
    runtime = ToolRuntime(workspace, manifest(), enforce_faulty_commit=False)
    real_run = subprocess.run
    commands: list[list[str]] = []

    def capture(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return real_run(command, **kwargs)

    monkeypatch.setattr("coderca.tool_runtime.subprocess.run", capture)

    _, payload = execute_search(
        runtime,
        tmp_path,
        {"query": "needle", "search_kind": "content"},
    )

    assert payload.status == "matched"
    assert all("--no-config" in command for command in commands)


def test_content_search_stops_after_global_result_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    source_directory = workspace / "src"
    source_directory.mkdir(parents=True)
    for index in range(10):
        (source_directory / f"module_{index}.py").write_text("needle = True\n")
    runtime = ToolRuntime(workspace, manifest(), enforce_faulty_commit=False)
    searched_files: list[str] = []

    def one_match(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        del kwargs
        relative_path = command[-1]
        searched_files.append(relative_path)
        event = {
            "type": "match",
            "data": {
                "path": {"text": relative_path},
                "lines": {"text": "needle = True\n"},
                "line_number": 1,
            },
        }
        return subprocess.CompletedProcess(
            command, 0, stdout=json.dumps(event) + "\n", stderr=""
        )

    monkeypatch.setattr("coderca.tool_runtime.subprocess.run", one_match)

    _, payload = execute_search(
        runtime,
        tmp_path,
        {
            "query": "needle",
            "search_kind": "content",
            "max_results": 2,
        },
    )

    assert len(payload.matches) == 2
    assert payload.truncated is True
    assert len(searched_files) == 3


def test_path_search_does_not_require_utf8_file_contents(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    binary = workspace / "src" / "compiled.pyc"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"\xff\xfe\x00\x01")
    runtime = ToolRuntime(workspace, manifest(), enforce_faulty_commit=False)

    result, payload = execute_search(
        runtime,
        tmp_path,
        {"query": "compiled.pyc", "search_kind": "path"},
    )

    assert result.status == "success"
    assert payload.status == "matched"
    assert payload.matches[0].path == "src/compiled.pyc"
