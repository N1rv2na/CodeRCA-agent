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
    assert manifest.tool_call_limit == 10


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
    "order",
    [("search_code", "read_code"), ("read_code", "search_code"), ("read_code",)],
)
@pytest.mark.parametrize("repair_passes", [True, False])
def test_task_2_autonomous_order_and_acceptance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    order: tuple[str, ...],
    repair_passes: bool,
) -> None:
    from coderca.task_2_acceptance import check_task_2_run, main

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
                    "root_symbol": "Switch",
                    "location_description": "waffle/utils.py",
                    "mechanism": truth.defect_mechanism,
                    "falsification_criterion": "Cache keys preserve case.",
                }
            },
            "generate_patch_intent": {
                "hypothesis_id": "H1",
                "target_path": "waffle/utils.py",
                "mechanism": truth.reference_repair_behavior,
                "edits": [
                    {
                        "old_text": "k % v.lower()",
                        "new_text": "k % v",
                    }
                ],
            },
            "generate_report": {
                "trigger_condition": truth.trigger_condition,
                "propagation_path": truth.propagation_path,
                "failure_manifestation": truth.failure_manifestation,
                "repair_recommendation": truth.reference_repair_behavior,
                "location": {
                    "path": "waffle/utils.py",
                    "symbol": "keyfmt",
                    "start_line": 25,
                    "end_line": 25,
                    "evidence_refs": [
                        f"E{order.index('read_code') + 1}",
                        f"E{len(order) + 1}",
                    ],
                },
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
                for i in range(1, len(order) + 1)
            ],
            "assess_hypothesis": (
                [
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
                ]
                if len(order) == 2
                else [
                    {
                        "outcome": "sufficiently_supported",
                        "evidence_refs": ["E1"],
                        "rationale": "The actual implementation proves the collision.",
                    }
                ]
            ),
        },
    )
    correction_expected = order == ("read_code",) and repair_passes
    if correction_expected:
        valid_report = provider.structured_responses["generate_report"]
        assert isinstance(valid_report, dict)
        bad_report = {
            **valid_report,
            "location": {**valid_report["location"], "evidence_refs": ["E999"]},
        }
        provider.structured_response_sequences["generate_report"] = [
            bad_report,
            valid_report,
        ]
    real_run = subprocess.run

    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if argv[0] == "docker":
            mount = argv[argv.index("--mount") + 1]
            source = next(
                p.removeprefix("src=") for p in mount.split(",") if p.startswith("src=")
            )
            assert "v.lower()" not in (Path(source) / "waffle/utils.py").read_text()
            if not repair_passes:
                return subprocess.CompletedProcess(
                    argv, 1, stdout="validation deliberately failed\n"
                )
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
    assert result.validation is not None
    assert result.validation.status == ("passed" if repair_passes else "failed")
    assert [o.source for o in result.observations] == [*order, "public_validation"]
    checked = check_task_2_run(result.run_directory)
    assert checked["outcome_pass"] is repair_passes, checked
    assert checked["location"] == "hit"
    assert checked["search_capability"] == (
        "verified" if "search_code" in order else "not_demonstrated"
    )
    assert result.hypothesis_history[0].root_symbol == "Switch"
    assert provider.structured_calls.count("generate_report") == (
        2 if correction_expected else 1
    )
    assert main([str(result.run_directory)]) == (0 if repair_passes else 1)
    assert main([str(result.run_directory), "--require-search"]) == (
        0 if repair_passes and "search_code" in order else 1
    )
    assert checked["audit_error"] is None
    if not repair_passes:
        return
    if order == ("read_code", "search_code"):
        events = [
            json.loads(line) for line in result.events_path.read_text().splitlines()
        ]
        assessment_event = [
            event for event in events if event["event_type"] == "hypothesis_assessed"
        ][-1]
        assessment_path = (
            result.run_directory / assessment_event["model_response_artifact"]
        )
        original_assessment = assessment_path.read_text()
        assessment = json.loads(original_assessment)
        assessment["evidence_refs"] = ["E1"]
        assessment_path.write_text(json.dumps(assessment))
        unused_search = check_task_2_run(result.run_directory)
        assert unused_search["outcome_pass"] is True
        assert unused_search["search_capability"] == "not_demonstrated"
        assessment_path.write_text(original_assessment)
    report = json.loads(result.report_path.read_text())
    report["root_cause_analysis"]["location"]["symbol"] = "Switch"
    result.report_path.write_text(json.dumps(report))
    assert check_task_2_run(result.run_directory)["outcome_pass"] is False
    report["root_cause_analysis"]["location"]["symbol"] = "keyfmt"
    result.report_path.write_text(json.dumps(report))
    original = result.report_path.read_text()
    report["root_cause_analysis"].pop("location")
    result.report_path.write_text(json.dumps(report))
    assert check_task_2_run(result.run_directory)["location"] == "not_provided"
    report = json.loads(original)
    report["evidence"] = [
        e for e in report["evidence"] if not e["provenance"].startswith("search_code:")
    ]
    result.report_path.write_text(json.dumps(report))
    if "search_code" in order:
        assert check_task_2_run(result.run_directory)["audit_error"]
    result.report_path.write_text(original)
    for field in ("validation", "patch"):
        broken = json.loads(original)
        broken[field] = None
        result.report_path.write_text(json.dumps(broken))
        assert check_task_2_run(result.run_directory)["outcome_pass"] is False
    broken = json.loads(original)
    broken["validation"]["status"] = "failed"
    broken["validation"]["failure_message"] = "registered test failed"
    result.report_path.write_text(json.dumps(broken))
    assert check_task_2_run(result.run_directory)["outcome_pass"] is False
    result.report_path.write_text(original)
    if "search_code" not in order:
        return
    search = next(o for o in result.observations if o.source == "search_code")
    search_path = result.run_directory / search.artifact_ref
    malformed_values: tuple[object, ...] = (
        [],
        None,
        {"status": "matched", "matches": "invalid"},
    )
    for malformed in malformed_values:
        search_path.write_text(json.dumps(malformed))
        assert check_task_2_run(result.run_directory)["outcome_pass"] is False
    (result.run_directory / search.artifact_ref).unlink()
    assert check_task_2_run(result.run_directory)["outcome_pass"] is False
