from __future__ import annotations

import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from coderca import benchmark
from coderca.application import DiagnosisApplicationService
from coderca.context_builder import resolve_task_context
from coderca.contracts import EvaluationGroundTruth, RegisteredTestCommand
from coderca.model_provider import FakeModelProvider
from coderca.run_store import RunStore
from coderca.tool_runtime import ToolRuntime, load_registered_test_command

TASK = Path("benchmarks/django-waffle/task-3")


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


def test_task_3_freezes_isolated_inputs_and_reuses_runtime_boundary() -> None:
    assert hasattr(benchmark, "load_task_3_manifest"), "Task 3 intake is missing"
    manifest = benchmark.load_task_3_manifest()
    truth = EvaluationGroundTruth.model_validate_json(
        (TASK / "ground_truth.json").read_text()
    )
    first = benchmark.load_task_1_manifest()
    second = benchmark.load_task_2_manifest()

    assert manifest.base_snapshot == first.base_snapshot == second.base_snapshot
    assert manifest.docker_image == first.docker_image == second.docker_image
    assert manifest.faulty_commit not in {first.faulty_commit, second.faulty_commit}
    assert manifest.test_command_id not in {
        first.test_command_id,
        second.test_command_id,
    }
    initial = (TASK / manifest.ci_log).read_text()
    assert truth.root_symbol not in initial
    assert "waffle/decorators.py" not in initial
    assert "direct_flag_state" not in initial
    assert "waffle_flag" not in manifest.model_dump_json()
    assert manifest.read_paths == ["waffle/"]
    assert manifest.write_paths == ["waffle/"]
    assert manifest.tool_call_limit == 10


def test_task_3_base_passes_faulty_fails_repeatedly_and_reference_repair_passes(
    tmp_path: Path,
) -> None:
    assert hasattr(benchmark, "materialize_task_3"), "Task 3 bundle is missing"
    base = benchmark.materialize_task_3(tmp_path / "base", snapshot="base")
    faulty = benchmark.materialize_task_3(tmp_path / "faulty")

    assert run_probe(base).returncode == 0
    failures = [run_probe(faulty) for _ in range(3)]
    assert all(result.returncode == 1 for result in failures)
    assert all(
        "CRCA_TASK_3_EXPECTED_ASSERTION_MISMATCH" in result.stdout
        and "direct_flag_state=False" in result.stdout
        and "inverse_guard_denied=True" in result.stdout
        and not result.stderr
        for result in failures
    )
    assert len({result.stdout for result in failures}) == 1

    subprocess.run(
        ["git", "apply", str((TASK / "reference.patch").resolve())],
        cwd=faulty,
        check=True,
    )
    assert run_probe(faulty).returncode == 0
    for author_only in ("ground_truth.json", "reference.patch", "probe.py"):
        assert not (faulty / author_only).exists()


def test_task_3_registered_probe_is_author_owned_and_reuses_image() -> None:
    command = json.loads((TASK / "registered-command.json").read_text())
    assert command["argv"] == ["python", "-c", (TASK / "probe.py").read_text()]
    assert "shell" not in command
    assert benchmark.load_task_3_manifest().docker_image == (
        benchmark.load_task_1_manifest().docker_image
    )


def test_task_3_registered_diagnostics_fit_bounded_observation_context() -> None:
    command = RegisteredTestCommand.model_validate_json(
        (TASK / "registered-command.json").read_text()
    )
    diagnostic_output = (
        "CRCA_TASK_3_EXPECTED_ASSERTION_MISMATCH\n"
        "configured_everyone=False\n"
        "direct_flag_state=False\n"
        "positive_guard_denied=True\n"
        "inverse_guard_denied=True\n"
    )
    artifact = ToolRuntime._format_test_artifact(  # noqa: SLF001
        command,
        exit_code=1,
        output=diagnostic_output,
    )
    bounded_context = artifact[:2_000]
    assert "direct_flag_state=False" in bounded_context
    assert "inverse_guard_denied=True" in bounded_context


def _run_accepted_task_3(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, FakeModelProvider]:
    from coderca.task_3_acceptance import check_task_3_run

    workspace = benchmark.materialize_task_3(tmp_path / "workspace")
    manifest = benchmark.load_task_3_manifest()
    truth = EvaluationGroundTruth.model_validate_json(
        (TASK / "ground_truth.json").read_text()
    )
    provider = FakeModelProvider(
        structured_responses={
            "form_hypothesis": {
                "hypothesis": {
                    "root_symbol": "flag_is_active",
                    "location_description": (
                        "Flag state resolution for inactive records"
                    ),
                    "mechanism": (
                        "The underlying flag evaluator returns True for a persisted "
                        "inactive flag, so the guarded request is denied."
                    ),
                    "falsification_criterion": (
                        "A direct lookup returning False while the inverse guard still "
                        "denies the request falsifies this evaluator mechanism."
                    ),
                }
            },
            "reformulate_hypothesis": {
                "hypothesis": {
                    "root_symbol": None,
                    "location_description": "Inverse flag guard polarity",
                    "mechanism": truth.defect_mechanism,
                    "falsification_criterion": (
                        "The inverse branch explicitly negates the direct flag result."
                    ),
                },
                "evidence_refs": ["E1"],
            },
            "generate_patch_intent": {
                "hypothesis_id": "H2",
                "target_path": "waffle/decorators.py",
                "mechanism": truth.reference_repair_behavior,
                "edits": [
                    {
                        "old_text": (
                            "active = flag_is_active(request, flag_name[1:])"
                        ),
                        "new_text": (
                            "active = not flag_is_active(request, flag_name[1:])"
                        ),
                    }
                ],
            },
            "generate_report": {
                "trigger_condition": truth.trigger_condition,
                "propagation_path": truth.propagation_path,
                "failure_manifestation": truth.failure_manifestation,
                "repair_recommendation": truth.reference_repair_behavior,
                "location": {
                    "path": "waffle/decorators.py",
                    "symbol": "waffle_flag",
                    "start_line": 20,
                    "end_line": 20,
                    "evidence_refs": ["E3"],
                },
            },
        },
        structured_response_sequences={
            "select_experiment": [
                {
                    "hypothesis_id": "H1",
                    "purpose": (
                        "Run the registered probe to compare direct flag state with "
                        "the guarded request."
                    ),
                    "expected_observation": (
                        "The direct evaluator returns False while the inverse guard "
                        "still denies the request."
                    ),
                    "falsification_relevance": (
                        "A correct direct False result contradicts H1's evaluator bug."
                    ),
                    "tool_name": "run_tests",
                    "arguments": {"test_command_id": manifest.test_command_id},
                },
                {
                    "hypothesis_id": "H2",
                    "purpose": (
                        "Search for the legacy route before reading the decorator."
                    ),
                    "expected_observation": (
                        "A route match identifies the guard site; no match leaves "
                        "the decorator implementation unresolved."
                    ),
                    "falsification_relevance": (
                        "A correctly wired route guard would contradict H2."
                    ),
                    "tool_name": "search_code",
                    "arguments": {
                        "query": "legacy-dashboard",
                        "search_kind": "content",
                        "path": "waffle/",
                        "context_lines": 2,
                        "max_results": 5,
                    },
                },
                {
                    "hypothesis_id": "H2",
                    "purpose": (
                        "Read the inverse decorator branch after H1 is rejected."
                    ),
                    "expected_observation": (
                        "The inverse branch reuses the direct result without "
                        "negating it."
                    ),
                    "falsification_relevance": (
                        "An explicit logical negation would falsify H2."
                    ),
                    "tool_name": "read_code",
                    "arguments": {
                        "path": "waffle/decorators.py",
                        "start_line": 13,
                        "end_line": 31,
                    },
                },
            ],
            "update_evidence": [
                {
                    "hypothesis_id": "H1",
                    "observation_ref": "O1",
                    "direction": "contradicting",
                    "explanation": (
                        "The direct evaluator returns False as configured, while the "
                        "inverse guard alone denies access; this contradicts H1."
                    ),
                },
                {
                    "hypothesis_id": "H2",
                    "observation_ref": "O2",
                    "direction": "inconclusive",
                    "explanation": (
                        "The bounded route-name search returned no matches and "
                        "does not resolve the decorator polarity."
                    ),
                },
                {
                    "hypothesis_id": "H2",
                    "observation_ref": "O3",
                    "direction": "supporting",
                    "explanation": truth.defect_mechanism,
                },
            ],
            "assess_hypothesis": [
                {
                    "outcome": "falsified",
                    "evidence_refs": ["E1"],
                    "rationale": (
                        "E1 directly contradicts the Flag evaluator mechanism."
                    ),
                },
                {
                    "outcome": "continue_testing",
                    "evidence_refs": ["E2"],
                    "rationale": (
                        "E2 is bounded and inconclusive; a distinct decorator "
                        "inspection remains available."
                    ),
                },
                {
                    "outcome": "sufficiently_supported",
                    "evidence_refs": ["E3"],
                    "rationale": "E3 directly shows the missing inverse operation.",
                },
            ],
        },
    )
    real_run = subprocess.run

    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if argv[0] != "docker":
            return real_run(argv, **kwargs)
        mount = argv[argv.index("--mount") + 1]
        source = Path(
            next(
                part.removeprefix("src=")
                for part in mount.split(",")
                if part.startswith("src=")
            )
        )
        source_text = (source / "waffle/decorators.py").read_text()
        if any("compile(" in item for item in argv):
            return subprocess.CompletedProcess(argv, 0, stdout="STATIC_OK\n")
        if "active = not flag_is_active(request, flag_name[1:])" in source_text:
            return subprocess.CompletedProcess(
                argv, 0, stdout="CRCA_TASK_3_OK\n"
            )
        return subprocess.CompletedProcess(
            argv,
            1,
            stdout=(
                "CRCA_TASK_3_EXPECTED_ASSERTION_MISMATCH\n"
                "configured_everyone=False\n"
                "direct_flag_state=False\n"
                "positive_guard_denied=True\n"
                "inverse_guard_denied=True\n"
            ),
        )

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

    checked = check_task_3_run(result.run_directory)
    assert checked["trajectory_pass"] is True, checked
    assert checked["outcome_pass"] is True, checked
    return result.run_directory, provider


def test_task_3_fake_run_proves_bounded_self_correction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from coderca.task_3_acceptance import check_task_3_run, main

    run_directory, provider = _run_accepted_task_3(tmp_path, monkeypatch)
    checked = check_task_3_run(run_directory)
    report = json.loads((run_directory / "report.json").read_text())

    assert checked == {
        "audit_error": None,
        "causal_review": "required",
        "h1_falsified": True,
        "h2_reformulated": True,
        "human_review_required": True,
        "outcome_pass": True,
        "repair_validation": "passed",
        "trajectory_pass": True,
    }
    assert [item["status"] for item in report["hypothesis_history"]] == [
        "rejected",
        "supported",
    ]
    assert report["hypothesis_history"][0]["evidence_basis"] == []
    assert report["hypothesis_history"][1]["evidence_basis"] == ["E1"]
    assert report["evidence"][0]["direction"] == "contradicting"
    assert report["evidence"][0]["hypothesis_id"] == "H1"
    assert report["observations"][0]["source"] == "run_tests"
    assert report["patch"]["hypothesis_id"] == "H2"
    assert report["validation"]["hypothesis_id"] == "H2"
    assert provider.structured_calls.index("reformulate_hypothesis") > (
        provider.structured_calls.index("assess_hypothesis")
    )
    assert main([str(run_directory)]) == 0


@pytest.mark.parametrize(
    "corruption",
    [
        "parallel_active",
        "h1_free_text_basis",
        "h2_missing_basis",
        "h2_unknown_basis",
        "h2_duplicate_basis",
        "h1_revival",
        "h4",
        "h1_not_rejected_at_assessment",
        "reformulation_event_missing_h2",
        "preterminal_assessment_not_continue_testing",
        "duplicate_supported_assessment",
        "patch_before_h2_supported",
        "validation_before_h2_supported",
    ],
)
def test_task_3_acceptance_rejects_illegal_hypothesis_trajectory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    corruption: str,
) -> None:
    from coderca.task_3_acceptance import check_task_3_run

    run_directory, _ = _run_accepted_task_3(tmp_path, monkeypatch)
    report_path = run_directory / "report.json"
    events_path = run_directory / "events.jsonl"
    report = json.loads(report_path.read_text())
    events = [json.loads(line) for line in events_path.read_text().splitlines()]

    if corruption == "parallel_active":
        event = next(e for e in events if e["event_type"] == "hypothesis_reformulated")
        event["hypothesis_history"][0]["status"] = "proposed"
    elif corruption == "h1_free_text_basis":
        report["hypothesis_history"][0]["evidence_basis"] = ["CI log says 404"]
    elif corruption == "h2_missing_basis":
        report["hypothesis_history"][1]["evidence_basis"] = []
    elif corruption == "h2_unknown_basis":
        report["hypothesis_history"][1]["evidence_basis"] = ["E999"]
    elif corruption == "h2_duplicate_basis":
        report["hypothesis_history"][1]["evidence_basis"] = ["E1", "E1"]
    elif corruption == "h1_revival":
        event = deepcopy(events[-1])
        event["sequence"] = len(events) + 1
        event["event_type"] = "hypothesis_reformed_illegally"
        event["hypothesis_history"][0]["status"] = "proposed"
        events.append(event)
    elif corruption == "h4":
        h4 = deepcopy(report["hypothesis_history"][1])
        h4["hypothesis_id"] = "H4"
        h4["status"] = "rejected"
        report["hypothesis_history"].append(h4)
    elif corruption == "h1_not_rejected_at_assessment":
        event = next(e for e in events if e["event_type"] == "hypothesis_assessed")
        event["hypothesis_history"][-1]["status"] = "proposed"
    elif corruption == "reformulation_event_missing_h2":
        event = next(
            e for e in events if e["event_type"] == "hypothesis_reformulated"
        )
        event["hypothesis_history"] = event["hypothesis_history"][:1]
    elif corruption == "preterminal_assessment_not_continue_testing":
        event = next(
            e
            for e in events
            if e["event_type"] == "hypothesis_assessed"
            and e["hypothesis_history"][-1]["status"] == "testing"
        )
        artifact_path = run_directory / event["model_response_artifact"]
        response = json.loads(artifact_path.read_text())
        response["outcome"] = "sufficiently_supported"
        artifact_path.write_text(json.dumps(response))
    elif corruption == "duplicate_supported_assessment":
        supported_index = next(
            index
            for index, event in enumerate(events)
            if event["event_type"] == "hypothesis_assessed"
            and event["hypothesis_history"][-1]["status"] == "supported"
        )
        events.insert(supported_index + 1, deepcopy(events[supported_index]))
        for sequence, event in enumerate(events, start=1):
            event["sequence"] = sequence
    elif corruption in {
        "patch_before_h2_supported",
        "validation_before_h2_supported",
    }:
        event_type = (
            "patch_generated"
            if corruption == "patch_before_h2_supported"
            else "validation_completed"
        )
        premature_index = next(
            index
            for index, event in enumerate(events)
            if event["event_type"] == event_type
        )
        premature = events.pop(premature_index)
        assessment_index = next(
            index
            for index, event in enumerate(events)
            if event["event_type"] == "hypothesis_assessed"
        )
        premature["hypothesis_history"] = deepcopy(
            events[assessment_index - 1]["hypothesis_history"]
        )
        events.insert(assessment_index, premature)
        for sequence, event in enumerate(events, start=1):
            event["sequence"] = sequence
    else:  # pragma: no cover
        raise AssertionError(corruption)

    report_path.write_text(json.dumps(report))
    events_path.write_text("".join(json.dumps(event) + "\n" for event in events))
    checked = check_task_3_run(run_directory)
    assert checked["trajectory_pass"] is False
    assert checked["outcome_pass"] is False
    assert checked["audit_error"]
