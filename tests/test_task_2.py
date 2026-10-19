from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from coderca import benchmark
from coderca.application import DiagnosisApplicationService
from coderca.context_builder import resolve_task_context
from coderca.contracts import EvaluationGroundTruth, RegisteredTestCommand, TaskManifest
from coderca.model_provider import FakeModelProvider
from coderca.run_store import RunStore
from coderca.tool_runtime import ToolRuntime, load_registered_test_command

TASK = Path("benchmarks/django-waffle/task-2")


def test_task_2_freezes_independent_inputs_without_initial_root_location() -> None:
    assert hasattr(benchmark, "load_task_2_manifest"), "Task 2 intake is missing"
    manifest = benchmark.load_task_2_manifest()
    truth = EvaluationGroundTruth.model_validate_json(
        (TASK / "ground_truth.json").read_text()
    )
    first = benchmark.load_task_1_manifest()
    assert manifest.base_snapshot == first.base_snapshot
    assert manifest.docker_image == first.docker_image
    assert manifest.faulty_commit != first.faulty_commit
    assert manifest.test_command_id != first.test_command_id
    initial = (TASK / manifest.ci_log).read_text()
    assert truth.root_symbol not in initial
    assert "waffle/utils.py" not in initial
    assert "keyfmt" not in manifest.model_dump_json()
    assert manifest.read_paths == ["waffle/"]
    assert manifest.write_paths == ["waffle/"]


def run_probe(workspace: Path) -> subprocess.CompletedProcess[str]:
    command = RegisteredTestCommand.model_validate_json(
        (TASK / "registered-command.json").read_text()
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(workspace)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, *command.argv[1:]],
        cwd=workspace,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_task_2_base_passes_faulty_fails_and_reference_repair_passes(
    tmp_path: Path,
) -> None:
    assert hasattr(benchmark, "materialize_task_2"), "Task 2 bundle is missing"
    base = benchmark.materialize_task_2(tmp_path / "base", snapshot="base")
    faulty = benchmark.materialize_task_2(tmp_path / "faulty")
    assert run_probe(base).returncode == 0
    outputs = [run_probe(faulty) for _ in range(3)]
    manifest = TaskManifest.model_validate_json((TASK / "manifest.json").read_text())
    expected = (TASK / manifest.ci_log).read_text()
    assert all(result.returncode == 1 for result in outputs)
    assert all(result.stdout == expected and not result.stderr for result in outputs)
    subprocess.run(
        ["git", "apply", str((TASK / "reference.patch").resolve())],
        cwd=faulty,
        check=True,
    )
    assert run_probe(faulty).returncode == 0
    assert not (faulty / "ground_truth.json").exists()
    assert not (faulty / "reference.patch").exists()


def test_task_2_registered_probe_is_author_owned_and_reuses_image() -> None:
    assert (TASK / "registered-command.json").exists()
    command = json.loads((TASK / "registered-command.json").read_text())
    assert command["argv"] == ["python", "-c", (TASK / "probe.py").read_text()]
    assert "shell" not in command


@pytest.mark.parametrize(
    "order", [("search_code", "read_code"), ("read_code", "search_code")]
)
def test_task_2_autonomous_order_and_acceptance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, order: tuple[str, str]
) -> None:
    from coderca.task_2_acceptance import check_task_2_run

    workspace = benchmark.materialize_task_2(tmp_path / "workspace")
    manifest = benchmark.load_task_2_manifest()
    truth = EvaluationGroundTruth.model_validate_json(
        (TASK / "ground_truth.json").read_text()
    )
    selections: list[dict[str, Any]] = []
    for tool in order:
        selections.append(
            {
                "hypothesis_id": "H1",
                "tool_name": tool,
                "purpose": "Trace case-sensitive names into shared cache identity.",
                "expected_observation": "Callers share a case-normalizing cache key.",
                "falsification_relevance": "Preserving case in keys would falsify H1.",
                "arguments": (
                    {
                        "query": "keyfmt",
                        "search_kind": "content",
                        "max_results": 20,
                        "context_lines": 2,
                    }
                    if tool == "search_code"
                    else {"path": "waffle/utils.py", "start_line": 19, "end_line": 25}
                ),
            }
        )
    provider = FakeModelProvider(
        structured_responses={
            "form_hypothesis": {
                "hypothesis": {
                    "root_symbol": "keyfmt",
                    "location_description": "waffle/utils.py",
                    "mechanism": truth.defect_mechanism,
                    "falsification_criterion": "Cache keys preserve case.",
                }
            },
            "generate_patch": {
                "hypothesis_id": "H1",
                "target_path": "waffle/utils.py",
                "mechanism": truth.reference_repair_behavior,
                "unified_diff": (TASK / "reference.patch").read_text(),
            },
            "generate_report": {
                "trigger_condition": truth.trigger_condition,
                "propagation_path": truth.propagation_path,
                "failure_manifestation": truth.failure_manifestation,
                "repair_recommendation": truth.reference_repair_behavior,
            },
        },
        structured_response_sequences={
            "select_experiment": selections,
            "update_evidence": [
                {
                    "hypothesis_id": "H1",
                    "observation_ref": f"O{i}",
                    "direction": "supporting",
                    "explanation": truth.defect_mechanism,
                }
                for i in (1, 2)
            ],
            "assess_hypothesis": [
                {
                    "outcome": "continue_testing",
                    "evidence_refs": ["E1"],
                    "rationale": "Need both caller and implementation evidence.",
                },
                {
                    "outcome": "sufficiently_supported",
                    "evidence_refs": ["E1", "E2"],
                    "rationale": "Search links callers; code shows the collision.",
                },
            ],
        },
    )
    real_run = subprocess.run

    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if argv[0] == "docker":
            mount = argv[argv.index("--mount") + 1]
            source = next(
                p.removeprefix("src=") for p in mount.split(",") if p.startswith("src=")
            )
            assert "v.lower()" not in (Path(source) / "waffle/utils.py").read_text()
            return subprocess.CompletedProcess(argv, 0, stdout="CRCA_TASK_2_OK\n")
        return real_run(argv, **kwargs)

    monkeypatch.setattr("coderca.tool_runtime.subprocess.run", run)
    result = DiagnosisApplicationService(
        provider=provider,
        run_store=RunStore(tmp_path / "runs"),
        tool_runtime=ToolRuntime(
            workspace,
            manifest,
            registered_test_command=load_registered_test_command(
                TASK / "registered-command.json",
                expected_command_id=manifest.test_command_id,
            ),
        ),
    ).start_diagnosis(resolve_task_context(manifest, TASK))
    assert result.validation is not None and result.validation.status == "passed"
    assert [o.source for o in result.observations] == [*order, "public_validation"]
    assert check_task_2_run(result.run_directory)["structural_pass"] is True
    report = json.loads(result.report_path.read_text())
    report["final_hypothesis"]["root_symbol"] = "Switch"
    result.report_path.write_text(json.dumps(report))
    assert check_task_2_run(result.run_directory)["structural_pass"] is False
    report["final_hypothesis"]["root_symbol"] = "keyfmt"
    result.report_path.write_text(json.dumps(report))
    original = result.report_path.read_text()
    report["evidence"] = [
        e for e in report["evidence"] if not e["provenance"].startswith("search_code:")
    ]
    result.report_path.write_text(json.dumps(report))
    assert check_task_2_run(result.run_directory)["trajectory_pass"] is False
    result.report_path.write_text(original)
    for field in ("validation", "patch"):
        broken = json.loads(original)
        broken[field] = None
        result.report_path.write_text(json.dumps(broken))
        assert check_task_2_run(result.run_directory)["structural_pass"] is False
    broken = json.loads(original)
    broken["validation"]["status"] = "failed"
    broken["validation"]["failure_message"] = "registered test failed"
    result.report_path.write_text(json.dumps(broken))
    assert check_task_2_run(result.run_directory)["structural_pass"] is False
    result.report_path.write_text(original)
    search = next(o for o in result.observations if o.source == "search_code")
    search_path = result.run_directory / search.artifact_ref
    malformed_values: tuple[object, ...] = (
        [],
        None,
        {"status": "matched", "matches": "invalid"},
    )
    for malformed in malformed_values:
        search_path.write_text(json.dumps(malformed))
        assert check_task_2_run(result.run_directory)["structural_pass"] is False
    (result.run_directory / search.artifact_ref).unlink()
    assert check_task_2_run(result.run_directory)["structural_pass"] is False
