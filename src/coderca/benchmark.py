"""Frozen CRCA-002 benchmark task and its registered test boundary.

This module owns task intake and deterministic materialization only.  It does
not implement a Tool Runtime or a Diagnosis Agent.  The benchmark repository
is distributed as a small git bundle containing the approved upstream base
commit and one synthetic Faulty Commit.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Literal

from .contracts import TaskManifest

REPOSITORY_URL = "https://github.com/django-waffle/django-waffle.git"
REPOSITORY_ID = "django-waffle"
UPSTREAM_RELEASE = "v5.0.0"
BASE_COMMIT_SHA = "2ca9a74a90957c79322d6a9b063213258feff908"
FAULTY_COMMIT_SHA = "51e2424a0a6d8817291e5696b0cfbb1b3384a699"
TASK_1_ID = "crca-002-task-1"
TASK_1_COMMAND_ID = "django_waffle_task_1_v1"
TASK_1_CI_LOG = "ci/task-1-failure.log"
DOCKER_IMAGE = "coderca/django-waffle-task-1:5.0.0-py311-v2"
TASK_2_FAULTY_COMMIT_SHA = "30c21019633ddd5e60d3628c08692e404ea03d55"
TASK_3_FAULTY_COMMIT_SHA = "17f2b840e6f39ef0773abb7b4618acfb9f6a6bc7"
TASK_1_READ_PATHS = ("waffle/",)
TASK_1_WRITE_PATHS = ("waffle/models.py",)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_BUNDLE_PATH = (
    _PROJECT_ROOT / "benchmarks" / "django-waffle" / "task-1" / "task-1.bundle"
)
_MANIFEST_PATH = (
    _PROJECT_ROOT / "benchmarks" / "django-waffle" / "task-1" / "manifest.json"
)


def load_task_1_manifest() -> TaskManifest:
    """Load and validate the single Agent-visible source of Task 1 metadata."""

    manifest = TaskManifest.model_validate_json(_MANIFEST_PATH.read_text())
    validate_task_1_inputs(manifest)
    return manifest


def validate_task_1_inputs(manifest: TaskManifest) -> None:
    """Reject manifests that escape the approved repository/task boundary."""

    if manifest.task_id != TASK_1_ID:
        raise ValueError("task ID is not the frozen Task 1 identifier")
    if manifest.repository_id != REPOSITORY_ID:
        raise ValueError("repository is not the frozen django-waffle repository")
    if manifest.base_snapshot != BASE_COMMIT_SHA:
        raise ValueError("base snapshot is not the frozen upstream v5.0.0 commit")
    if manifest.faulty_commit != FAULTY_COMMIT_SHA:
        raise ValueError("faulty commit does not match the frozen Task 1 commit")
    if manifest.test_command_id != TASK_1_COMMAND_ID:
        raise ValueError("command is not a registered Task 1 command")
    if manifest.ci_log != TASK_1_CI_LOG:
        raise ValueError("CI log is not the frozen Task 1 failure artifact")
    if manifest.docker_image != DOCKER_IMAGE:
        raise ValueError("Docker image is not the frozen Task 1 image")
    if manifest.tool_call_limit != 10:
        raise ValueError("tool call limit is not the frozen Task 1 budget")
    for candidate in manifest.read_paths:
        if candidate.startswith("/") or ".." in Path(candidate).parts:
            raise ValueError("read path escapes the frozen repository boundary")
    if tuple(manifest.read_paths) != TASK_1_READ_PATHS:
        raise ValueError("read path is outside the registered Task 1 source")
    for candidate in manifest.write_paths:
        if candidate.startswith("/") or ".." in Path(candidate).parts:
            raise ValueError("write path escapes the frozen repository boundary")
    if tuple(manifest.write_paths) != TASK_1_WRITE_PATHS:
        raise ValueError("write path is outside the registered Task 1 business source")


def materialize_task_1(
    destination: Path,
    *,
    faulty_commit: str = FAULTY_COMMIT_SHA,
    snapshot: Literal["base", "faulty"] = "faulty",
) -> Path:
    """Clone the bundled history and check out the requested task snapshot."""

    if faulty_commit != FAULTY_COMMIT_SHA:
        raise ValueError("faulty commit does not match the frozen Task 1 commit")
    if not _BUNDLE_PATH.is_file():
        raise FileNotFoundError(f"benchmark bundle is missing: {_BUNDLE_PATH}")
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(
            f"materialization destination already exists: {destination}"
        )

    _run_git(["clone", str(_BUNDLE_PATH), str(destination)], cwd=_PROJECT_ROOT)
    target_commit = BASE_COMMIT_SHA if snapshot == "base" else FAULTY_COMMIT_SHA
    _run_git(["checkout", "--detach", target_commit], cwd=destination)
    checked_out = _git_output(["rev-parse", "HEAD"], cwd=destination)
    if checked_out != target_commit:
        raise RuntimeError("materialized checkout did not reach the requested snapshot")
    return destination


def _run_git(arguments: list[str], *, cwd: Path) -> None:
    subprocess.run(
        ["git", *arguments], cwd=cwd, check=True, capture_output=True, text=True
    )


def load_task_2_manifest() -> TaskManifest:
    """Load the independent frozen code-exploration task."""
    directory = _PROJECT_ROOT / "benchmarks/django-waffle/task-2"
    manifest = TaskManifest.model_validate_json(
        (directory / "manifest.json").read_text()
    )
    expected = {
        "schema_version": "1",
        "task_id": "crca-010-task-2",
        "repository_id": REPOSITORY_ID,
        "base_snapshot": BASE_COMMIT_SHA,
        "faulty_commit": TASK_2_FAULTY_COMMIT_SHA,
        "ci_log": "ci/task-2-failure.log",
        "test_command_id": "django_waffle_task_2_v1",
        "docker_image": DOCKER_IMAGE,
        "read_paths": ["waffle/"],
        "write_paths": ["waffle/"],
        "tool_call_limit": 10,
    }
    if manifest.model_dump(mode="json") != expected:
        raise ValueError("manifest does not match the frozen Task 2 boundary")
    return manifest


def materialize_task_2(
    destination: Path, *, snapshot: Literal["base", "faulty"] = "faulty"
) -> Path:
    """Materialize Task 2 without author-only probes, truth, or repair artifacts."""
    load_task_2_manifest()
    if snapshot not in ("base", "faulty"):
        raise ValueError("unknown Task 2 snapshot")
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(
            f"materialization destination already exists: {destination}"
        )
    bundle = _PROJECT_ROOT / "benchmarks/django-waffle/task-2/task-2.bundle"
    _run_git(["clone", str(bundle), str(destination)], cwd=_PROJECT_ROOT)
    target = BASE_COMMIT_SHA if snapshot == "base" else TASK_2_FAULTY_COMMIT_SHA
    _run_git(["checkout", "--detach", target], cwd=destination)
    if _git_output(["rev-parse", "HEAD"], cwd=destination) != target:
        raise RuntimeError("materialized checkout did not reach the requested snapshot")
    return destination


def load_task_3_manifest() -> TaskManifest:
    """Load the independent frozen bounded-self-correction task."""
    directory = _PROJECT_ROOT / "benchmarks/django-waffle/task-3"
    manifest = TaskManifest.model_validate_json(
        (directory / "manifest.json").read_text()
    )
    expected = {
        "schema_version": "1",
        "task_id": "crca-011-task-3",
        "repository_id": REPOSITORY_ID,
        "base_snapshot": BASE_COMMIT_SHA,
        "faulty_commit": TASK_3_FAULTY_COMMIT_SHA,
        "ci_log": "ci/task-3-failure.log",
        "test_command_id": "django_waffle_task_3_v1",
        "docker_image": DOCKER_IMAGE,
        "read_paths": ["waffle/"],
        "write_paths": ["waffle/"],
        "tool_call_limit": 10,
    }
    if manifest.model_dump(mode="json") != expected:
        raise ValueError("manifest does not match the frozen Task 3 boundary")
    return manifest


def materialize_task_3(
    destination: Path, *, snapshot: Literal["base", "faulty"] = "faulty"
) -> Path:
    """Materialize Task 3 without author-only probe, truth, or repair files."""
    load_task_3_manifest()
    if snapshot not in ("base", "faulty"):
        raise ValueError("unknown Task 3 snapshot")
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(
            f"materialization destination already exists: {destination}"
        )
    bundle = _PROJECT_ROOT / "benchmarks/django-waffle/task-3/task-3.bundle"
    _run_git(["clone", str(bundle), str(destination)], cwd=_PROJECT_ROOT)
    target = BASE_COMMIT_SHA if snapshot == "base" else TASK_3_FAULTY_COMMIT_SHA
    _run_git(["checkout", "--detach", target], cwd=destination)
    if _git_output(["rev-parse", "HEAD"], cwd=destination) != target:
        raise RuntimeError("materialized checkout did not reach the requested snapshot")
    return destination


def _git_output(arguments: list[str], *, cwd: Path) -> str:
    result = subprocess.run(
        ["git", *arguments], cwd=cwd, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()
