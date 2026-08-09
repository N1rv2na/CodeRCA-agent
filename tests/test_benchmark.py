from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from coderca.benchmark import (
    TASK_1_COMMAND_ID,
    TASK_1_GROUND_TRUTH,
    TASK_1_MANIFEST,
    BenchmarkGroundTruth,
    materialize_task_1,
    run_registered_command,
    validate_task_1_inputs,
)


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
    assert isinstance(TASK_1_GROUND_TRUTH, BenchmarkGroundTruth)
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
        run_registered_command(checkout, "arbitrary-shell")
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
        run_registered_command(checkout, TASK_1_COMMAND_ID) for _ in range(3)
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


def test_manifest_and_ground_truth_files_are_physically_separate() -> None:
    manifest_payload = json.loads(
        Path("benchmarks/django-waffle/task-1/manifest.json").read_text()
    )
    ground_truth_payload = json.loads(
        Path("benchmarks/django-waffle/task-1/ground_truth.json").read_text()
    )

    assert "root_symbol" not in manifest_payload
    assert "reference_repair_behavior" not in manifest_payload
    assert "faulty_commit" in manifest_payload
    assert ground_truth_payload["root_symbol"] == "AbstractBaseFlag.is_active_for_user"
    assert TASK_1_MANIFEST.model_dump(mode="json") == manifest_payload
    assert TASK_1_GROUND_TRUTH.model_dump(mode="json") == ground_truth_payload

    agent_visible_text = json.dumps(manifest_payload) + Path(
        "benchmarks/django-waffle/task-1/ci/task-1-failure.log"
    ).read_text()
    assert "AbstractBaseFlag" not in agent_visible_text
    assert "is_active_for_user" not in agent_visible_text
    assert "everyone is not None" not in agent_visible_text


def test_task_1_docker_build_inputs_are_frozen() -> None:
    task_directory = Path("benchmarks/django-waffle/task-1")
    dockerfile = (task_directory / "Dockerfile").read_text()
    requirements = (task_directory / "requirements.lock").read_text()

    assert dockerfile.startswith(
        "FROM python:3.11-slim-bookworm@"
        "sha256:b18992999dbe963a45a8a4da40ac2b1975be1a776d939d098c647482bcad5cba\n"
    )
    assert "--require-hashes -r requirements.lock" in dockerfile
    assert "Django==5.2.16" in requirements
    assert requirements.count("--hash=sha256:") == 3
