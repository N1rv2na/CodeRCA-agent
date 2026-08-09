"""Frozen CRCA-002 benchmark task and its registered test boundary.

This module owns task intake and deterministic materialization only.  It does
not implement a Tool Runtime or a Diagnosis Agent.  The benchmark repository
is distributed as a small git bundle containing the approved upstream base
commit and one synthetic Faulty Commit.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Literal

from pydantic import Field

from .contracts import ContractModel, TaskManifest

REPOSITORY_URL = "https://github.com/django-waffle/django-waffle.git"
REPOSITORY_ID = "django-waffle"
UPSTREAM_RELEASE = "v5.0.0"
BASE_COMMIT_SHA = "2ca9a74a90957c79322d6a9b063213258feff908"
FAULTY_COMMIT_SHA = "51e2424a0a6d8817291e5696b0cfbb1b3384a699"
TASK_1_ID = "crca-002-task-1"
TASK_1_COMMAND_ID = "django_waffle_task_1_v1"
TASK_1_CI_LOG = "ci/task-1-failure.log"
DOCKER_IMAGE = "coderca/django-waffle-task-1:5.0.0-py311-v1"
TASK_1_READ_PATHS = ["waffle/"]
TASK_1_WRITE_PATHS = ["waffle/models.py"]

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_BUNDLE_PATH = (
    _PROJECT_ROOT / "benchmarks" / "django-waffle" / "task-1" / "task-1.bundle"
)
_PROBE_PATH = _PROJECT_ROOT / "benchmarks" / "django-waffle" / "task-1" / "probe.py"


class BenchmarkGroundTruth(ContractModel):
    """Evaluation-only facts kept outside the Agent-visible Task Manifest."""

    schema_version: Literal["1"]
    task_id: str = Field(min_length=1)
    root_symbol: str = Field(min_length=1)
    trigger_condition: str = Field(min_length=1)
    defect_mechanism: str = Field(min_length=1)
    propagation_path: str = Field(min_length=1)
    failure_manifestation: str = Field(min_length=1)
    reference_repair_behavior: str = Field(min_length=1)


class RegisteredCommandObservation(ContractModel):
    """Sanitized result returned by the fixed Task 1 command."""

    command_id: str = Field(min_length=1)
    exit_code: int
    failure_manifestation: Literal["assertion_mismatch", "passed", "execution_failed"]
    output: str = ""


TASK_1_MANIFEST = TaskManifest.model_validate(
    {
        "schema_version": "1",
        "task_id": TASK_1_ID,
        "repository_id": REPOSITORY_ID,
        "base_snapshot": BASE_COMMIT_SHA,
        "faulty_commit": FAULTY_COMMIT_SHA,
        "ci_log": TASK_1_CI_LOG,
        "test_command_id": TASK_1_COMMAND_ID,
        "docker_image": DOCKER_IMAGE,
        "read_paths": TASK_1_READ_PATHS,
        "write_paths": TASK_1_WRITE_PATHS,
        "tool_call_limit": 8,
    }
)

TASK_1_GROUND_TRUTH = BenchmarkGroundTruth.model_validate(
    {
        "schema_version": "1",
        "task_id": TASK_1_MANIFEST.task_id,
        "root_symbol": "AbstractBaseFlag.is_active_for_user",
        "trigger_condition": (
            "A persisted Flag has everyone=False and superusers=True; the request "
            "actor is a superuser."
        ),
        "defect_mechanism": (
            "The Faulty Commit treats everyone=False as if no explicit everyone value "
            "were configured, "
            "so the later superusers branch returns True."
        ),
        "propagation_path": (
            "Flag.is_active delegates user evaluation to "
            "AbstractBaseFlag.is_active_for_user; the resulting True value activates "
            "a flag explicitly disabled for everyone."
        ),
        "failure_manifestation": (
            "The registered opaque probe expects False and observes True, producing "
            "an assertion mismatch."
        ),
        "reference_repair_behavior": (
            "Restore the explicit tri-state guard everyone is not None before "
            "authenticated, staff, "
            "and superuser checks."
        ),
    }
)


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
    if manifest.tool_call_limit != 8:
        raise ValueError("tool call limit is not the frozen Task 1 budget")
    for candidate in manifest.read_paths:
        if candidate.startswith("/") or ".." in Path(candidate).parts:
            raise ValueError("read path escapes the frozen repository boundary")
    if manifest.read_paths != TASK_1_READ_PATHS:
        raise ValueError("read path is outside the registered Task 1 source")
    for candidate in manifest.write_paths:
        if candidate.startswith("/") or ".." in Path(candidate).parts:
            raise ValueError("write path escapes the frozen repository boundary")
    if manifest.write_paths != TASK_1_WRITE_PATHS:
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


def run_registered_command(
    checkout: Path,
    command_id: str,
    *,
    timeout_seconds: float = 30.0,
) -> RegisteredCommandObservation:
    """Execute the one fixed Task 1 probe and sanitize its public failure output."""

    if command_id != TASK_1_COMMAND_ID:
        raise ValueError("command is not registered for Task 1")
    checkout = Path(checkout)
    if not checkout.is_dir():
        raise ValueError("checkout path is not a directory")
    if not _PROBE_PATH.is_file():
        raise FileNotFoundError(f"registered probe is missing: {_PROBE_PATH}")
    if _git_output(["rev-parse", "HEAD"], cwd=checkout) != FAULTY_COMMIT_SHA:
        raise ValueError("checkout is not the frozen Faulty Commit")

    env = os.environ.copy()
    source_root = str(_PROJECT_ROOT / "src")
    env["PYTHONPATH"] = os.pathsep.join(
        filter(None, [str(checkout), source_root, env.get("PYTHONPATH", "")])
    )
    process = subprocess.run(
        [sys.executable, str(_PROBE_PATH)],
        cwd=checkout,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    output = f"{process.stdout}{process.stderr}"
    if process.returncode == 0:
        manifestation: Literal[
            "assertion_mismatch", "passed", "execution_failed"
        ] = "passed"
    elif "AssertionError" in output or "FAIL" in output:
        manifestation = "assertion_mismatch"
    else:
        manifestation = "execution_failed"
    return RegisteredCommandObservation(
        command_id=command_id,
        exit_code=process.returncode,
        failure_manifestation=manifestation,
        output=_sanitize_probe_output(manifestation),
    )


def _sanitize_probe_output(
    manifestation: Literal["assertion_mismatch", "passed", "execution_failed"],
) -> str:
    if manifestation == "assertion_mismatch":
        return "FAIL: test_case_17\nAssertionError: expected false, observed true\n"
    if manifestation == "passed":
        return "PASS: test_case_17\n"
    return "Task 1 registered command failed to execute.\n"


def _run_git(arguments: list[str], *, cwd: Path) -> None:
    subprocess.run(
        ["git", *arguments], cwd=cwd, check=True, capture_output=True, text=True
    )


def _git_output(arguments: list[str], *, cwd: Path) -> str:
    result = subprocess.run(
        ["git", *arguments], cwd=cwd, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()
