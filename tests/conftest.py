from __future__ import annotations

import pytest


@pytest.fixture
def valid_manifest_data() -> dict[str, object]:
    return {
        "schema_version": "1",
        "task_id": "task-001",
        "repository_id": "repo-001",
        "base_snapshot": "base-commit",
        "faulty_commit": "faulty-commit",
        "ci_log": "pytest failed: expected 1, got 2",
        "test_command_id": "registered-tests",
        "docker_image": "python:3.10",
        "read_paths": ["src/"],
        "write_paths": [],
        "tool_call_limit": 8,
    }
