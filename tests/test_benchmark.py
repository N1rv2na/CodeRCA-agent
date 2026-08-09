from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Literal, NamedTuple

import pytest

from coderca.benchmark import (
    FAULTY_COMMIT_SHA,
    TASK_1_COMMAND_ID,
    load_task_1_manifest,
    materialize_task_1,
    validate_task_1_inputs,
)
from coderca.contracts import EvaluationGroundTruth

TASK_DIRECTORY = Path("benchmarks/django-waffle/task-1")
PROBE_PATH = TASK_DIRECTORY / "probe.py"
EXPECTED_FAILURE_MARKER = "CRCA_TASK_1_EXPECTED_ASSERTION_MISMATCH"
TASK_1_MANIFEST = load_task_1_manifest()
TASK_1_GROUND_TRUTH = EvaluationGroundTruth.model_validate_json(
    (TASK_DIRECTORY / "ground_truth.json").read_text()
)


class AuthoringObservation(NamedTuple):
    exit_code: int
    failure_manifestation: Literal[
        "assertion_mismatch", "passed", "execution_failed"
    ]
    output: str


def run_task_1_authoring_probe(checkout: Path) -> AuthoringObservation:
    """Verify the frozen fixture locally; this is not a Diagnosis Tool Runtime."""

    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=checkout,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if head != FAULTY_COMMIT_SHA:
        raise ValueError("checkout is not the frozen Faulty Commit")

    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        filter(None, [str(checkout), environment.get("PYTHONPATH", "")])
    )
    process = subprocess.run(
        [sys.executable, str(PROBE_PATH.resolve())],
        cwd=checkout,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    raw_output = f"{process.stdout}{process.stderr}"
    if process.returncode == 0:
        manifestation: Literal[
            "assertion_mismatch", "passed", "execution_failed"
        ] = "passed"
        output = "PASS: test_case_17\n"
    elif process.returncode == 1 and EXPECTED_FAILURE_MARKER in raw_output:
        manifestation = "assertion_mismatch"
        output = "FAIL: test_case_17\nAssertionError: expected false, observed true\n"
    else:
        manifestation = "execution_failed"
        output = "Task 1 authoring probe failed to execute.\n"
    return AuthoringObservation(process.returncode, manifestation, output)


def test_task_1_manifest_uses_the_frozen_waffle_snapshot() -> None:
    assert TASK_1_MANIFEST.repository_id == "django-waffle"
    assert TASK_1_MANIFEST.base_snapshot == "2ca9a74a90957c79322d6a9b063213258feff908"
    assert TASK_1_MANIFEST.faulty_commit
    assert TASK_1_MANIFEST.test_command_id == TASK_1_COMMAND_ID
    assert (
        TASK_1_MANIFEST.docker_image
        == "coderca/django-waffle-task-1:5.0.0-py311-v1"
    )
    assert TASK_1_MANIFEST.read_paths == ["waffle/"]
    assert TASK_1_MANIFEST.write_paths == ["waffle/models.py"]


def test_ground_truth_is_a_separate_contract_and_has_one_root_symbol() -> None:
    assert isinstance(TASK_1_GROUND_TRUTH, EvaluationGroundTruth)
    assert TASK_1_GROUND_TRUTH.task_id == TASK_1_MANIFEST.task_id
    assert TASK_1_GROUND_TRUTH.root_symbol == "AbstractBaseFlag.is_active_for_user"
    assert TASK_1_GROUND_TRUTH.reference_repair_behavior


def test_task_1_materializes_faulty_commit_and_rejects_tampered_inputs(
    tmp_path: Path,
) -> None:
    checkout = materialize_task_1(tmp_path / "checkout")
    base_checkout = materialize_task_1(tmp_path / "base", snapshot="base")

    assert (checkout / ".git").is_dir()
    assert (checkout / "waffle" / "models.py").is_file()
    assert (checkout / ".git" / "HEAD").is_file()
    assert base_checkout.is_dir()

    fsck = subprocess.run(
        ["git", "fsck", "--full"],
        cwd=checkout,
        capture_output=True,
        text=True,
        check=False,
    )
    assert fsck.returncode == 0, fsck.stderr

    commit_message = subprocess.run(
        ["git", "log", "-1", "--format=%s"],
        cwd=checkout,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert commit_message == "benchmark: task 1 snapshot"
    assert "everyone" not in commit_message
    assert "precedence" not in commit_message

    with pytest.raises(ValueError, match="faulty commit"):
        materialize_task_1(tmp_path / "tampered", faulty_commit="0" * 40)
    with pytest.raises(ValueError, match="command"):
        validate_task_1_inputs(
            TASK_1_MANIFEST.model_copy(update={"test_command_id": "arbitrary-shell"})
        )
    with pytest.raises(ValueError, match="path"):
        validate_task_1_inputs(
            TASK_1_MANIFEST.model_copy(update={"read_paths": ["../"]})
        )
    with pytest.raises(ValueError, match="write path"):
        validate_task_1_inputs(
            TASK_1_MANIFEST.model_copy(update={"write_paths": ["waffle/tests/"]})
        )
    with pytest.raises(ValueError, match="Docker image"):
        validate_task_1_inputs(
            TASK_1_MANIFEST.model_copy(update={"docker_image": "python:latest"})
        )
    with pytest.raises(ValueError, match="CI log"):
        validate_task_1_inputs(
            TASK_1_MANIFEST.model_copy(update={"ci_log": "ci/other.log"})
        )


def test_registered_task_1_command_fails_deterministically_three_times(
    tmp_path: Path,
) -> None:
    checkout = materialize_task_1(tmp_path / "checkout")

    observations = [
        run_task_1_authoring_probe(checkout) for _ in range(3)
    ]

    assert all(observation.exit_code != 0 for observation in observations)
    assert all(
        observation.failure_manifestation == "assertion_mismatch"
        for observation in observations
    )
    assert all(
        "AbstractBaseFlag" not in observation.output for observation in observations
    )
    assert all(
        "is_active_for_user" not in observation.output for observation in observations
    )


def test_registered_command_does_not_misclassify_environment_failure(
    tmp_path: Path,
) -> None:
    checkout = materialize_task_1(tmp_path / "checkout")
    (checkout / "test_settings.py").write_text(
        'raise RuntimeError("FAILED environment setup")\n'
    )

    observation = run_task_1_authoring_probe(checkout)

    assert observation.exit_code != 0
    assert observation.failure_manifestation == "execution_failed"


def test_manifest_and_ground_truth_files_are_physically_separate() -> None:
    manifest_payload = json.loads(
        (TASK_DIRECTORY / "manifest.json").read_text()
    )
    ground_truth_payload = json.loads(
        (TASK_DIRECTORY / "ground_truth.json").read_text()
    )

    assert "root_symbol" not in manifest_payload
    assert "reference_repair_behavior" not in manifest_payload
    assert "faulty_commit" in manifest_payload
    assert ground_truth_payload["root_symbol"] == "AbstractBaseFlag.is_active_for_user"
    assert TASK_1_MANIFEST.model_dump(mode="json") == manifest_payload
    assert TASK_1_GROUND_TRUTH.model_dump(mode="json") == ground_truth_payload

    agent_visible_text = json.dumps(manifest_payload) + (
        TASK_DIRECTORY / "ci" / "task-1-failure.log"
    ).read_text()
    task_intake_source = Path("src/coderca/benchmark.py").read_text()
    assert "AbstractBaseFlag" not in agent_visible_text
    assert "is_active_for_user" not in agent_visible_text
    assert "everyone is not None" not in agent_visible_text
    assert "AbstractBaseFlag.is_active_for_user" not in task_intake_source
    assert "everyone is not None" not in task_intake_source


def test_task_1_registered_command_is_fixed_argv_not_shell() -> None:
    command = json.loads((TASK_DIRECTORY / "registered-command.json").read_text())

    assert command == {
        "argv": ["python", "/opt/coderca-task/probe.py"],
        "command_id": TASK_1_COMMAND_ID,
        "schema_version": "1",
        "timeout_seconds": 30,
    }
    assert "shell" not in command


def test_task_1_docker_build_inputs_are_frozen() -> None:
    dockerfile = (TASK_DIRECTORY / "Dockerfile").read_text()
    requirements = (TASK_DIRECTORY / "requirements.lock").read_text()

    assert dockerfile.startswith(
        "FROM python:3.11-slim-bookworm@"
        "sha256:b18992999dbe963a45a8a4da40ac2b1975be1a776d939d098c647482bcad5cba\n"
    )
    assert "--require-hashes -r requirements.lock" in dockerfile
    assert "COPY probe.py ./probe.py" in dockerfile
    assert "Django==5.2.16" in requirements
    assert requirements.count("--hash=sha256:") == 3
