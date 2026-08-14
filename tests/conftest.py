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


@pytest.fixture
def valid_model_gate_responses() -> dict[str, dict[str, object]]:
    return {
        "preflight": {"status": "ok", "model_id": "example-model"},
        "stage_schema": {
            "stage": "hypothesis_generation",
            "next_action": "inspect_code",
            "reason": "The failing test requires code inspection.",
        },
        "tool_arguments": {
            "hypothesis_id": "H1",
            "purpose": "Inspect boolean precedence handling.",
            "expected_observation": "Find an explicit False handling branch.",
            "tool_name": "read_code",
            "arguments": {
                "path": "waffle/models.py",
                "start_line": 1,
                "end_line": 150,
            },
        },
        "evidence_update": {
            "hypothesis_id": "H1",
            "observation_ref": "obs-read-code-001",
            "direction": "contradicting",
            "evidence_summary": "The implementation checks against None.",
            "rationale": "Explicit False is preserved, contradicting the hypothesis.",
        },
        "python_patch": {
            "hypothesis_id": "H1",
            "target_path": "sample.py",
            "mechanism": "Preserve an explicit zero timeout.",
            "unified_diff": (
                "--- a/sample.py\n"
                "+++ b/sample.py\n"
                "@@ -1,2 +1,2 @@\n"
                " def select_timeout(configured: int | None, default: int) -> int:\n"
                "-    return configured or default\n"
                "+    return configured if configured is not None else default\n"
            ),
        },
    }
