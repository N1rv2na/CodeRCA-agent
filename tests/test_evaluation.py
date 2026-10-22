from __future__ import annotations

import json
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import pytest

from coderca.application import DiagnosisApplicationService
from coderca.benchmark import load_task_2_manifest, materialize_task_2
from coderca.context_builder import DiagnosisTaskContext
from coderca.contracts import (
    CandidatePatch,
    DiagnosisEvent,
    DiagnosisReport,
    DiagnosisStage,
    EvaluationGroundTruth,
    Evidence,
    ExactReplacement,
    Experiment,
    FinalRootCauseLocation,
    Hypothesis,
    Observation,
    PatchIntentDecision,
    PatchValidationAction,
    PublicValidationResult,
    ReportDecision,
    ToolResult,
    ValidationCheckResult,
)
from coderca.model_provider import FakeModelProvider
from coderca.run_store import RunStore
from coderca.tool_runtime import (
    SearchCodeResult,
    SearchMatch,
    ToolRuntime,
    load_registered_test_command,
)

BENCHMARK = Path("benchmarks/django-waffle")


def _write_valid_task_2_run(tmp_path: Path) -> Path:
    manifest = load_task_2_manifest()
    truth = EvaluationGroundTruth.model_validate_json(
        (BENCHMARK / "task-2/ground_truth.json").read_text()
    )
    store = RunStore(tmp_path / "runs")
    artifacts = store.create_run("run-1")
    store.write_manifest(artifacts, manifest)
    h1_proposed = Hypothesis(
        hypothesis_id="H1",
        root_symbol="Switch",
        location_description="waffle cache identity",
        mechanism=truth.defect_mechanism,
        falsification_criterion="Cache keys preserve case.",
    )
    h1_testing = h1_proposed.model_copy(update={"status": "testing"})
    h1_supported = h1_proposed.model_copy(update={"status": "supported"})
    experiment = Experiment(
        experiment_id="X1",
        hypothesis_id="H1",
        purpose="Read the cache key implementation.",
        expected_observation="The input name is lowercased before hashing.",
        falsification_relevance="Preserved case would falsify H1.",
        tool_name="read_code",
        arguments={"path": "waffle/utils.py", "start_line": 19, "end_line": 25},
    )
    code = (
        "19: def keyfmt(k: str, v: str | None = None) -> str:\n"
        "20:     prefix = get_setting('CACHE_PREFIX')\n"
        "21:     if v is None:\n"
        "22:         key = prefix + k\n"
        "23:     else:\n"
        "24:         value = k % v.lower()\n"
        "25:         key = prefix + hashlib.md5(value.encode()).hexdigest()\n"
    )
    code_ref = "tool-results/T1.txt"
    (artifacts.run_directory / "tool-results").mkdir()
    (artifacts.run_directory / code_ref).write_text(code)
    tool_result = ToolResult(
        tool_result_id="T1",
        experiment_id="X1",
        hypothesis_id="H1",
        tool_name="read_code",
        status="success",
        output=code,
        artifact_ref=code_ref,
        duration_ms=1,
    )
    observation = Observation(
        observation_id="O1",
        experiment_id="X1",
        hypothesis_id="H1",
        tool_result_ref="T1",
        source="read_code",
        summary="read_code completed",
        artifact_ref=code_ref,
        excerpt=code,
    )
    evidence = Evidence(
        evidence_id="E1",
        hypothesis_id="H1",
        observation_ref="O1",
        provenance=f"read_code:{code_ref}",
        direction="supporting",
        explanation=truth.defect_mechanism,
    )
    patch = CandidatePatch(
        hypothesis_id="H1",
        target_path="waffle/utils.py",
        mechanism=truth.reference_repair_behavior,
        unified_diff=(
            "--- a/waffle/utils.py\n+++ b/waffle/utils.py\n"
            "@@ -24 +24 @@\n-        value = k % v.lower()\n"
            "+        value = k % v\n"
        ),
    )
    action = PatchValidationAction(
        validation_action_id="V1",
        hypothesis_id="H1",
        purpose="Apply the Candidate Patch and run Public Validation.",
        tool_name="apply_patch",
        arguments={
            "target_path": patch.target_path,
            "unified_diff": patch.unified_diff,
        },
    )
    patch_ref = "patches/candidate.patch"
    validation_ref = "validation/result.json"
    static_ref = "validation/static.txt"
    test_ref = "validation/registered-test.txt"
    for directory in ("patches", "validation", "model-responses"):
        (artifacts.run_directory / directory).mkdir(exist_ok=True)
    (artifacts.run_directory / patch_ref).write_text(patch.unified_diff)
    (artifacts.run_directory / static_ref).write_text("STATIC_OK\n")
    (artifacts.run_directory / test_ref).write_text("CRCA_TASK_2_OK\n")
    validation = PublicValidationResult(
        hypothesis_id="H1",
        status="passed",
        patch_artifact_ref=patch_ref,
        artifact_ref=validation_ref,
        static_check=ValidationCheckResult(
            name="static_check", passed=True, exit_code=0, artifact_ref=static_ref
        ),
        registered_test=ValidationCheckResult(
            name="registered_test", passed=True, exit_code=0, artifact_ref=test_ref
        ),
    )
    (artifacts.run_directory / validation_ref).write_text(
        validation.model_dump_json(indent=2) + "\n"
    )
    validation_result = ToolResult(
        tool_result_id="T2",
        validation_action_id="V1",
        hypothesis_id="H1",
        tool_name="apply_patch",
        status="success",
        output=validation.model_dump_json(),
        artifact_ref=validation_ref,
        duration_ms=1,
    )
    validation_observation = Observation(
        observation_id="O2",
        validation_action_id="V1",
        hypothesis_id="H1",
        tool_result_ref="T2",
        source="public_validation",
        summary="Public Validation passed",
        artifact_ref=validation_ref,
        excerpt=validation.model_dump_json(),
    )
    validation_evidence = Evidence(
        evidence_id="E2",
        hypothesis_id="H1",
        observation_ref="O2",
        provenance=f"public_validation:{validation_ref}",
        direction="supporting",
        explanation="The Candidate Patch passed Public Validation.",
    )
    analysis = ReportDecision(
        trigger_condition=truth.trigger_condition,
        propagation_path=truth.propagation_path,
        failure_manifestation=truth.failure_manifestation,
        repair_recommendation=truth.reference_repair_behavior,
        location=FinalRootCauseLocation(
            path=truth.root_path,
            symbol=truth.root_symbol,
            start_line=truth.root_start_line,
            end_line=truth.root_end_line,
            evidence_refs=("E1",),
        ),
    )
    assessment_ref = "model-responses/04-assess-hypothesis.json"
    patch_intent_ref = "model-responses/05-generate-patch-intent.json"
    (artifacts.run_directory / assessment_ref).write_text(
        json.dumps(
            {
                "outcome": "sufficiently_supported",
                "evidence_refs": ["E1"],
                "rationale": "E1 directly supports H1.",
            }
        )
    )
    patch_intent = PatchIntentDecision(
        hypothesis_id="H1",
        target_path="waffle/utils.py",
        mechanism=truth.reference_repair_behavior,
        edits=(ExactReplacement(old_text="v.lower()", new_text="v"),),
    )
    (artifacts.run_directory / patch_intent_ref).write_text(
        patch_intent.model_dump_json()
    )
    common: dict[str, Any] = {"run_id": "run-1", "task_id": manifest.task_id}
    events = [
        DiagnosisEvent(
            sequence=1,
            event_type="run_started",
            stage=DiagnosisStage.PREPARING,
            message="Run started.",
            **common,
        ),
        DiagnosisEvent(
            sequence=2,
            event_type="hypothesis_formed",
            stage=DiagnosisStage.DIAGNOSING,
            message="H1 formed.",
            hypothesis_history=[h1_proposed],
            **common,
        ),
        DiagnosisEvent(
            sequence=3,
            event_type="tool_executed",
            stage=DiagnosisStage.EXECUTING_TOOL,
            message="read_code executed.",
            hypothesis_history=[h1_testing],
            experiment=experiment,
            tool_result=tool_result,
            **common,
        ),
        DiagnosisEvent(
            sequence=4,
            event_type="evidence_recorded",
            stage=DiagnosisStage.UPDATING_EVIDENCE,
            message="E1 recorded.",
            hypothesis_history=[h1_testing],
            experiment=experiment,
            observation=observation,
            evidence=evidence,
            **common,
        ),
        DiagnosisEvent(
            sequence=5,
            event_type="hypothesis_assessed",
            stage=DiagnosisStage.DIAGNOSING,
            message="H1 supported.",
            hypothesis_history=[h1_supported],
            model_response_artifact=assessment_ref,
            **common,
        ),
        DiagnosisEvent(
            sequence=6,
            event_type="patch_generated",
            stage=DiagnosisStage.VALIDATING,
            message="Patch compiled.",
            hypothesis_history=[h1_supported],
            model_response_artifact=patch_intent_ref,
            patch=patch,
            validation_action=action,
            **common,
        ),
        DiagnosisEvent(
            sequence=7,
            event_type="validation_completed",
            stage=DiagnosisStage.VALIDATING,
            message="Validation passed.",
            hypothesis_history=[h1_supported],
            patch=patch,
            validation=validation,
            validation_action=action,
            tool_result=validation_result,
            observation=validation_observation,
            evidence=validation_evidence,
            **common,
        ),
        DiagnosisEvent(
            sequence=8,
            event_type="report_generated",
            stage=DiagnosisStage.VALIDATING,
            message="Report generated.",
            hypothesis_history=[h1_supported],
            patch=patch,
            validation=validation,
            root_cause_analysis=analysis,
            **common,
        ),
        DiagnosisEvent(
            sequence=9,
            event_type="run_completed",
            stage=DiagnosisStage.FINALIZING,
            message="Run completed.",
            hypothesis_history=[h1_supported],
            patch=patch,
            validation=validation,
            root_cause_analysis=analysis,
            **common,
        ),
    ]
    report = DiagnosisReport(
        run_id="run-1",
        task_id=manifest.task_id,
        stage=DiagnosisStage.FINALIZING,
        status="completed",
        stop_reason="validation_passed",
        summary="Public Validation passed.",
        hypothesis_history=[h1_supported],
        final_hypothesis=h1_supported,
        observations=[observation, validation_observation],
        evidence=[evidence, validation_evidence],
        patch=patch,
        validation=validation,
        root_cause_analysis=analysis,
    )
    store.write_events(artifacts, events)
    store.write_report(artifacts, report)
    return artifacts.run_directory


def _read_report(run_directory: Path) -> dict[str, Any]:
    return cast(
        dict[str, Any], json.loads((run_directory / "report.json").read_text())
    )


def _write_report(run_directory: Path, value: dict[str, Any]) -> None:
    (run_directory / "report.json").write_text(json.dumps(value))


def _read_events(run_directory: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in (run_directory / "events.jsonl").read_text().splitlines()
    ]


def _write_events(run_directory: Path, values: list[dict[str, Any]]) -> None:
    (run_directory / "events.jsonl").write_text(
        "".join(json.dumps(value) + "\n" for value in values)
    )


@pytest.mark.parametrize(
    ("task", "path", "symbol", "line"),
    [
        ("task-1", "waffle/models.py", "AbstractBaseFlag.is_active_for_user", 234),
        ("task-2", "waffle/utils.py", "keyfmt", 25),
        ("task-3", "waffle/decorators.py", "waffle_flag", 20),
    ],
)
def test_frozen_ground_truth_contains_deterministic_root_location(
    task: str, path: str, symbol: str, line: int
) -> None:
    truth = EvaluationGroundTruth.model_validate_json(
        (BENCHMARK / task / "ground_truth.json").read_text()
    )

    assert truth.root_path == path
    assert truth.root_symbol == symbol
    assert truth.root_start_line <= line <= truth.root_end_line
    assert symbol in truth.accepted_root_symbols


def test_ground_truth_rejects_reversed_root_location() -> None:
    with pytest.raises(ValueError, match="root location line range is reversed"):
        EvaluationGroundTruth(
            schema_version="1",
            task_id="task",
            root_path="src/example.py",
            root_symbol="example",
            accepted_root_symbols=("example",),
            root_start_line=12,
            root_end_line=10,
            trigger_condition="A trigger occurs.",
            defect_mechanism="A defect exists.",
            propagation_path="The defect propagates.",
            failure_manifestation="The task fails.",
            reference_repair_behavior="Repair the defect.",
        )


def test_evaluate_run_separates_automated_results_from_causal_review(
    tmp_path: Path,
) -> None:
    from coderca.evaluation import CausalReviewRecord, evaluate_run

    run_directory = _write_valid_task_2_run(tmp_path)
    truth = EvaluationGroundTruth.model_validate_json(
        (BENCHMARK / "task-2/ground_truth.json").read_text()
    )

    pending = evaluate_run(run_directory, truth)

    assert pending.outcome.model_dump(mode="json") == {
        "location": "hit",
        "root_location": {
            "path": "waffle/utils.py",
            "symbol": "keyfmt",
            "start_line": 25,
            "end_line": 25,
            "evidence_refs": ["E1"],
        },
        "patch_intent_compilation": "passed",
        "candidate_patch": "applicable",
        "validation": "passed",
        "report_contract": "passed",
        "passed": True,
        "violations": [],
    }
    assert pending.trajectory.passed is True
    assert pending.trajectory.violations == ()
    assert pending.search_capability == "not_demonstrated"
    assert pending.causal_review.status == "pending"
    assert pending.accepted is False

    review = CausalReviewRecord(
        task_id=truth.task_id,
        reviewer="project-author",
        trigger_condition="match",
        defect_location="match",
        propagation_path="match",
        failure_manifestation="match",
        notes="Compared the structured report with frozen Ground Truth.",
    )
    reviewed = evaluate_run(run_directory, truth, causal_review=review)

    assert reviewed.outcome == pending.outcome
    assert reviewed.trajectory == pending.trajectory
    assert reviewed.causal_review.status == "passed"
    assert reviewed.accepted is True


@pytest.mark.parametrize(
    ("corruption", "field", "expected"),
    [
        ("location", "location", "miss"),
        ("report", "report_contract", "failed"),
        ("patch_intent", "patch_intent_compilation", "failed"),
        ("patch_compilation", "patch_intent_compilation", "failed"),
        ("patch_artifact", "candidate_patch", "invalid"),
        ("validation_artifact", "validation", "failed"),
    ],
)
def test_outcome_evaluation_reports_independent_failures(
    tmp_path: Path, corruption: str, field: str, expected: str
) -> None:
    from coderca.evaluation import evaluate_run

    run_directory = _write_valid_task_2_run(tmp_path)
    truth = EvaluationGroundTruth.model_validate_json(
        (BENCHMARK / "task-2/ground_truth.json").read_text()
    )
    report = _read_report(run_directory)
    if corruption == "location":
        report["root_cause_analysis"]["location"]["symbol"] = "Switch"
        _write_report(run_directory, report)
    elif corruption == "report":
        report["root_cause_analysis"] = None
        _write_report(run_directory, report)
    elif corruption == "patch_intent":
        patch_event = next(
            event
            for event in _read_events(run_directory)
            if event["event_type"] == "patch_generated"
        )
        (run_directory / patch_event["model_response_artifact"]).write_text("{}")
    elif corruption == "patch_compilation":
        patch_event = next(
            event
            for event in _read_events(run_directory)
            if event["event_type"] == "patch_generated"
        )
        intent_path = run_directory / patch_event["model_response_artifact"]
        intent = json.loads(intent_path.read_text())
        intent["edits"][0]["old_text"] = "does_not_exist()"
        intent_path.write_text(json.dumps(intent))
    elif corruption == "patch_artifact":
        (run_directory / report["validation"]["patch_artifact_ref"]).write_text(
            "not the Candidate Patch\n"
        )
    elif corruption == "validation_artifact":
        (run_directory / report["validation"]["artifact_ref"]).write_text("{}")
    else:  # pragma: no cover
        raise AssertionError(corruption)

    result = evaluate_run(run_directory, truth)

    assert getattr(result.outcome, field) == expected
    assert result.outcome.passed is False
    if corruption not in {"location", "report"}:
        assert result.outcome.location == "hit"


@pytest.mark.parametrize(
    ("corruption", "violation"),
    [
        ("parallel_active", "multiple_active_hypotheses"),
        ("history_overwrite", "hypothesis_identity_changed"),
        ("revival", "terminal_hypothesis_revived"),
        ("h4", "invalid_hypothesis_budget"),
        ("unbound_experiment", "invalid_experiment_binding"),
        ("missing_falsification_relevance", "experiment_metadata_missing"),
        ("evidence_provenance", "invalid_evidence_provenance"),
        ("premature_reformulation", "reformulated_before_current_hypothesis_ended"),
        ("tool_budget", "tool_budget_exceeded"),
        ("illegal_stop", "illegal_stop_event"),
        ("non_supported_patch", "non_supported_hypothesis_patch"),
        ("validation_hypothesis", "non_supported_hypothesis_patch"),
        ("assessment_evidence", "invalid_hypothesis_assessment"),
        ("future_assessment_evidence", "invalid_hypothesis_assessment"),
        ("stop_reason", "illegal_stop_reason"),
        ("premature_tool_budget_stop", "illegal_stop_reason"),
    ],
)
def test_trajectory_evaluation_detects_illegal_run_artifacts(
    tmp_path: Path, corruption: str, violation: str
) -> None:
    from coderca.evaluation import evaluate_run

    run_directory = _write_valid_task_2_run(tmp_path)
    truth = EvaluationGroundTruth.model_validate_json(
        (BENCHMARK / "task-2/ground_truth.json").read_text()
    )
    report = _read_report(run_directory)
    events = _read_events(run_directory)
    tool_event = next(
        event for event in events if event["event_type"] == "tool_executed"
    )
    patch_event = next(
        event for event in events if event["event_type"] == "patch_generated"
    )
    if corruption == "parallel_active":
        h2 = deepcopy(tool_event["hypothesis_history"][0])
        h2["hypothesis_id"] = "H2"
        h2["status"] = "proposed"
        tool_event["hypothesis_history"].append(h2)
    elif corruption == "history_overwrite":
        tool_event["hypothesis_history"][0]["mechanism"] = "Overwritten mechanism"
    elif corruption == "revival":
        patch_event["hypothesis_history"][0]["status"] = "proposed"
    elif corruption == "h4":
        report["hypothesis_history"] = []
        for index in range(1, 5):
            hypothesis = deepcopy(report["final_hypothesis"])
            hypothesis["hypothesis_id"] = f"H{index}"
            hypothesis["status"] = "rejected"
            hypothesis["evidence_basis"] = [] if index == 1 else ["E1"]
            report["hypothesis_history"].append(hypothesis)
        _write_report(run_directory, report)
    elif corruption == "unbound_experiment":
        tool_event["experiment"]["hypothesis_id"] = "H2"
        tool_event["tool_result"]["hypothesis_id"] = "H2"
    elif corruption == "missing_falsification_relevance":
        del tool_event["experiment"]["falsification_relevance"]
    elif corruption == "evidence_provenance":
        report["evidence"][0]["provenance"] = "read_code:tool-results/other.txt"
        _write_report(run_directory, report)
    elif corruption == "premature_reformulation":
        h2 = deepcopy(tool_event["hypothesis_history"][0])
        h2["hypothesis_id"] = "H2"
        h2["status"] = "proposed"
        premature = deepcopy(tool_event)
        premature["event_type"] = "hypothesis_reformulated"
        premature["experiment"] = None
        premature["tool_result"] = None
        premature["hypothesis_history"] = [
            tool_event["hypothesis_history"][0],
            h2,
        ]
        events.insert(2, premature)
    elif corruption == "tool_budget":
        for _ in range(10):
            events.insert(-1, deepcopy(tool_event))
    elif corruption == "illegal_stop":
        events[-1]["event_type"] = "run_failed"
    elif corruption == "non_supported_patch":
        patch_event["hypothesis_history"][0]["status"] = "testing"
    elif corruption == "validation_hypothesis":
        validation_event = next(
            event
            for event in events
            if event["event_type"] == "validation_completed"
        )
        validation_event["validation"]["hypothesis_id"] = "H2"
    elif corruption == "assessment_evidence":
        assessment_event = next(
            event
            for event in events
            if event["event_type"] == "hypothesis_assessed"
        )
        assessment_path = run_directory / assessment_event["model_response_artifact"]
        assessment = json.loads(assessment_path.read_text())
        assessment["evidence_refs"] = ["E999"]
        assessment_path.write_text(json.dumps(assessment))
    elif corruption == "future_assessment_evidence":
        evidence_index = next(
            index
            for index, event in enumerate(events)
            if event["event_type"] == "evidence_recorded"
        )
        assessment_index = next(
            index
            for index, event in enumerate(events)
            if event["event_type"] == "hypothesis_assessed"
        )
        events[evidence_index], events[assessment_index] = (
            events[assessment_index],
            events[evidence_index],
        )
    elif corruption == "stop_reason":
        report["stop_reason"] = "tool_failure"
        _write_report(run_directory, report)
    elif corruption == "premature_tool_budget_stop":
        report["stop_reason"] = "tool_budget_exhausted"
        _write_report(run_directory, report)
    else:  # pragma: no cover
        raise AssertionError(corruption)
    for sequence, event in enumerate(events, start=1):
        event["sequence"] = sequence
    _write_events(run_directory, events)

    result = evaluate_run(run_directory, truth)

    assert result.trajectory.passed is False
    assert violation in result.trajectory.violations
    assert result.accepted is False


def test_evaluation_rejects_run_manifest_that_is_not_the_frozen_task(
    tmp_path: Path,
) -> None:
    from coderca.evaluation import evaluate_run

    run_directory = _write_valid_task_2_run(tmp_path)
    truth = EvaluationGroundTruth.model_validate_json(
        (BENCHMARK / "task-2/ground_truth.json").read_text()
    )
    manifest = json.loads((run_directory / "manifest.json").read_text())
    manifest["faulty_commit"] = manifest["base_snapshot"]
    (run_directory / "manifest.json").write_text(json.dumps(manifest))

    with pytest.raises(ValueError, match="canonical frozen task"):
        evaluate_run(run_directory, truth)


def test_failed_run_cannot_be_accepted_with_success_artifacts(tmp_path: Path) -> None:
    from coderca.evaluation import CausalReviewRecord, evaluate_run

    run_directory = _write_valid_task_2_run(tmp_path)
    truth = EvaluationGroundTruth.model_validate_json(
        (BENCHMARK / "task-2/ground_truth.json").read_text()
    )
    report = _read_report(run_directory)
    report["status"] = "failed"
    report["stop_reason"] = "tool_failure"
    _write_report(run_directory, report)
    events = _read_events(run_directory)
    events[-1]["event_type"] = "run_failed"
    _write_events(run_directory, events)
    review = CausalReviewRecord(
        task_id=truth.task_id,
        reviewer="project-author",
        trigger_condition="match",
        defect_location="match",
        propagation_path="match",
        failure_manifestation="match",
    )

    result = evaluate_run(run_directory, truth, causal_review=review)

    assert result.outcome.passed is False
    assert result.trajectory.passed is False
    assert "illegal_stop_reason" in result.trajectory.violations
    assert result.accepted is False


def test_search_capability_is_independent_and_requires_used_search_evidence(
    tmp_path: Path,
) -> None:
    from coderca.evaluation import evaluate_run

    run_directory = _write_valid_task_2_run(tmp_path)
    truth = EvaluationGroundTruth.model_validate_json(
        (BENCHMARK / "task-2/ground_truth.json").read_text()
    )
    report = _read_report(run_directory)
    events = _read_events(run_directory)
    search = SearchCodeResult(
        query="keyfmt",
        search_kind="content",
        path="waffle/utils.py",
        status="matched",
        matches=(
            SearchMatch(
                path="waffle/utils.py",
                start_line=23,
                end_line=25,
                snippet="23: else:\n24: value = k % v.lower()\n25: key = ...\n",
                truncated=False,
            ),
        ),
        truncated=False,
    )
    payload = search.model_dump_json()
    tool_event = next(
        event for event in events if event["event_type"] == "tool_executed"
    )
    evidence_event = next(
        event for event in events if event["event_type"] == "evidence_recorded"
    )
    tool_event["experiment"]["tool_name"] = "search_code"
    tool_event["experiment"]["arguments"] = {
        "query": "keyfmt",
        "search_kind": "content",
        "path": "waffle/utils.py",
        "max_results": 10,
        "context_lines": 2,
    }
    tool_event["tool_result"]["tool_name"] = "search_code"
    tool_event["tool_result"]["output"] = payload
    evidence_event["experiment"] = tool_event["experiment"]
    evidence_event["observation"]["source"] = "search_code"
    evidence_event["observation"]["excerpt"] = payload
    evidence_event["evidence"]["provenance"] = (
        "search_code:tool-results/T1.txt"
    )
    report["observations"][0] = evidence_event["observation"]
    report["evidence"][0] = evidence_event["evidence"]
    (run_directory / "tool-results/T1.txt").write_text(payload)
    _write_events(run_directory, events)
    _write_report(run_directory, report)

    result = evaluate_run(run_directory, truth)

    assert result.outcome.passed is True
    assert result.search_capability == "verified"


def test_evaluation_harness_runs_through_diagnosis_application_service(
    tmp_path: Path,
) -> None:
    from coderca.evaluation import EvaluationCase, EvaluationHarness

    manifest = load_task_2_manifest()
    truth = EvaluationGroundTruth.model_validate_json(
        (BENCHMARK / "task-2/ground_truth.json").read_text()
    )
    provider = FakeModelProvider()
    service = DiagnosisApplicationService(
        provider=provider,
        run_store=RunStore(tmp_path / "runs"),
    )
    task = DiagnosisTaskContext(
        manifest=manifest,
        ci_failure_excerpt="AssertionError: second lookup returned the first state",
        ci_failure_artifact=manifest.ci_log,
    )

    result = EvaluationHarness().run_case(
        service,
        EvaluationCase(task=task, ground_truth=truth),
    )

    assert provider.structured_calls == ["form_hypothesis"]
    assert result.task_id == manifest.task_id
    assert result.outcome.passed is False
    assert result.run_directory.startswith(str(tmp_path / "runs"))


def test_evaluation_harness_accepts_complete_fake_model_application_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from coderca.evaluation import (
        CausalReviewRecord,
        EvaluationCase,
        EvaluationHarness,
    )

    manifest = load_task_2_manifest()
    truth = EvaluationGroundTruth.model_validate_json(
        (BENCHMARK / "task-2/ground_truth.json").read_text()
    )
    workspace = materialize_task_2(tmp_path / "workspace")
    command = load_registered_test_command(
        BENCHMARK / "task-2/registered-command.json",
        expected_command_id=manifest.test_command_id,
    )
    provider = FakeModelProvider(
        {
            "form_hypothesis": {
                "hypothesis": {
                    "root_symbol": "keyfmt",
                    "location_description": "waffle/utils.py cache key formatting",
                    "mechanism": truth.defect_mechanism,
                    "falsification_criterion": "The input name preserves case.",
                }
            },
            "select_experiment": {
                "hypothesis_id": "H1",
                "purpose": "Read the cache key implementation.",
                "expected_observation": "The input name is lowercased.",
                "falsification_relevance": "Preserved case would falsify H1.",
                "tool_name": "read_code",
                "arguments": {
                    "path": "waffle/utils.py",
                    "start_line": 19,
                    "end_line": 25,
                },
            },
            "update_evidence": {
                "hypothesis_id": "H1",
                "observation_ref": "O1",
                "direction": "supporting",
                "explanation": truth.defect_mechanism,
            },
            "assess_hypothesis": {
                "outcome": "sufficiently_supported",
                "evidence_refs": ["E1"],
                "rationale": "E1 directly shows the lowercasing defect.",
            },
            "generate_patch_intent": {
                "hypothesis_id": "H1",
                "target_path": "waffle/utils.py",
                "mechanism": truth.reference_repair_behavior,
                "edits": [{"old_text": "v.lower()", "new_text": "v"}],
            },
            "generate_report": {
                "trigger_condition": truth.trigger_condition,
                "propagation_path": truth.propagation_path,
                "failure_manifestation": truth.failure_manifestation,
                "repair_recommendation": truth.reference_repair_behavior,
                "location": {
                    "path": truth.root_path,
                    "symbol": truth.root_symbol,
                    "start_line": truth.root_start_line,
                    "end_line": truth.root_end_line,
                    "evidence_refs": ["E1"],
                },
            },
        }
    )
    real_run = subprocess.run

    def run(command_line: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if command_line[0] == "git":
            return cast(
                subprocess.CompletedProcess[str], real_run(command_line, **kwargs)
            )
        assert command_line[0] == "docker"
        return subprocess.CompletedProcess(
            command_line, 0, stdout="CRCA_TASK_2_OK\n"
        )

    monkeypatch.setattr("coderca.tool_runtime.subprocess.run", run)
    service = DiagnosisApplicationService(
        provider=provider,
        run_store=RunStore(tmp_path / "runs"),
        tool_runtime=ToolRuntime(
            workspace,
            manifest,
            registered_test_command=command,
        ),
    )
    review = CausalReviewRecord(
        task_id=truth.task_id,
        reviewer="project-author",
        trigger_condition="match",
        defect_location="match",
        propagation_path="match",
        failure_manifestation="match",
    )
    task = DiagnosisTaskContext(
        manifest=manifest,
        ci_failure_excerpt="Case-distinct switches collide in cache.",
        ci_failure_artifact=manifest.ci_log,
    )

    result = EvaluationHarness().run_case(
        service,
        EvaluationCase(task=task, ground_truth=truth, causal_review=review),
    )

    assert result.accepted is True
    assert result.outcome.passed is True
    assert result.trajectory.passed is True
    assert provider.structured_calls == [
        "form_hypothesis",
        "select_experiment",
        "update_evidence",
        "assess_hypothesis",
        "generate_patch_intent",
        "generate_report",
    ]


def test_evaluation_cli_reports_per_task_without_aggregate_metrics(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from coderca.evaluation_cli import main

    run_directory = _write_valid_task_2_run(tmp_path)
    review_path = tmp_path / "causal-review.json"
    review_path.write_text(
        json.dumps(
            {
                "task_id": "crca-010-task-2",
                "reviewer": "project-author",
                "trigger_condition": "match",
                "defect_location": "match",
                "propagation_path": "match",
                "failure_manifestation": "match",
            }
        )
    )

    exit_code = main(
        [
            "--run-directory",
            str(run_directory),
            "--causal-review",
            str(review_path),
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["schema_version"] == "1"
    assert [item["task_id"] for item in payload["tasks"]] == [
        "crca-010-task-2"
    ]
    assert "success_rate" not in payload
    assert "total" not in payload


def test_evaluation_cli_requires_completed_causal_review(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from coderca.evaluation_cli import main

    run_directory = _write_valid_task_2_run(tmp_path)

    exit_code = main(["--run-directory", str(run_directory)])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["tasks"][0]["causal_review"]["status"] == "pending"
    assert payload["tasks"][0]["accepted"] is False
