from __future__ import annotations

from pathlib import Path

import pytest

from coderca.context_builder import (
    ContextBuilder,
    DiagnosisTaskContext,
    resolve_task_context,
)
from coderca.contracts import (
    Evidence,
    Experiment,
    FormHypothesisDecision,
    HypothesisAssessmentDecision,
    HypothesisProposal,
    Observation,
    TaskManifest,
    ToolResult,
    UpdateEvidenceDecision,
)
from coderca.diagnosis_state import DiagnosisStateMachine


def manifest() -> TaskManifest:
    return TaskManifest(
        schema_version="1",
        task_id="task-001",
        repository_id="repo-001",
        base_snapshot="base",
        faulty_commit="faulty",
        ci_log="ci/failure.log",
        test_command_id="tests",
        docker_image="image:locked",
        read_paths=["src/"],
        write_paths=["src/module.py"],
        tool_call_limit=8,
    )


def proposal(index: int) -> HypothesisProposal:
    return HypothesisProposal(
        location_description=f"module branch {index}",
        mechanism=f"mechanism {index}",
        falsification_criterion=f"criterion {index}",
    )


def state_with_h1() -> DiagnosisStateMachine:
    state = DiagnosisStateMachine()
    state.begin_hypothesis_formation()
    state.form_initial_hypothesis(FormHypothesisDecision(hypothesis=proposal(1)))
    return state


def task_context() -> DiagnosisTaskContext:
    return DiagnosisTaskContext(
        manifest=manifest(),
        ci_failure_excerpt="AssertionError: expected false, observed true",
        ci_failure_artifact="ci/failure.log",
    )


def diagnostic_records() -> tuple[Experiment, Observation, Evidence]:
    experiment = Experiment(
        experiment_id="X1",
        hypothesis_id="H1",
        purpose="Inspect the branch most likely to falsify H1.",
        expected_observation="The branch preserves explicit false.",
        falsification_relevance="That observation directly contradicts H1.",
        tool_name="read_code",
        arguments={"path": "src/module.py", "start_line": 1, "end_line": 80},
    )
    observation = Observation(
        observation_id="O1",
        experiment_id="X1",
        hypothesis_id="H1",
        tool_result_ref="T1",
        source="read_code",
        summary="The branch checks `value is not None`.",
        artifact_ref="tool-results/O1.txt",
        excerpt="x" * 4_000,
    )
    evidence = Evidence(
        evidence_id="E1",
        hypothesis_id="H1",
        observation_ref="O1",
        provenance="read_code:tool-results/O1.txt",
        direction="contradicting",
        explanation="The explicit false value is preserved, falsifying H1.",
    )
    return experiment, observation, evidence


def test_h1_context_contains_task_and_budgets_without_history() -> None:
    state = DiagnosisStateMachine()

    context = ContextBuilder().build_form_hypothesis(task_context(), state)

    assert context["decision_type"] == "form_hypothesis"
    assert context["diagnosis_state"]["hypothesis_history"] == []
    assert context["diagnosis_state"]["remaining_hypothesis_budget"] == 3
    assert context["diagnosis_state"]["remaining_tool_budget"] == 8
    assert context["task_context"]["ci_failure"]["excerpt"].startswith(
        "AssertionError"
    )
    assert "conversation_history" not in context
    assert "model_responses" not in context


def test_experiment_context_contains_only_active_hypothesis_knowledge() -> None:
    state = state_with_h1()
    experiment, observation, evidence = diagnostic_records()

    context = ContextBuilder().build_select_experiment(
        task_context(),
        state,
        available_tools=[
            {
                "name": "read_code",
                "description": "Read bounded source lines.",
                "input_schema": {"type": "object"},
                "permission": "read_only",
                "side_effects": "none",
            }
        ],
        experiments=[experiment],
        observations=[observation],
        evidence=[evidence],
        used_tool_calls=1,
    )

    assert context["active_hypothesis"]["hypothesis_id"] == "H1"
    assert context["active_hypothesis"]["falsification_criterion"] == "criterion 1"
    assert context["relevant_evidence"][0]["evidence_id"] == "E1"
    assert context["relevant_observations"][0]["observation_id"] == "O1"
    assert context["diagnosis_state"]["remaining_tool_budget"] == 7
    assert context["available_tools"][0]["name"] == "read_code"


def test_evidence_context_contains_experiment_and_bounded_observation() -> None:
    state = state_with_h1()
    experiment, observation, evidence = diagnostic_records()

    context = ContextBuilder(observation_excerpt_limit=200).build_update_evidence(
        task_context(),
        state,
        experiment=experiment,
        latest_observation=observation,
        evidence=[evidence],
    )

    assert context["current_experiment"]["experiment_id"] == "X1"
    assert context["latest_observation"]["artifact_ref"] == "tool-results/O1.txt"
    assert len(context["latest_observation"]["excerpt"]) == 200
    assert context["latest_observation"]["truncated"] is True
    assert context["existing_relevant_evidence"][0]["evidence_id"] == "E1"


def test_assessment_context_contains_only_active_hypothesis_knowledge() -> None:
    state = state_with_h1()
    _, observation, evidence = diagnostic_records()

    context = ContextBuilder().build_assess_hypothesis(
        task_context(),
        state,
        observations=[observation],
        evidence=[evidence],
        used_tool_calls=2,
    )

    assert context["decision_type"] == "assess_hypothesis"
    assert context["active_hypothesis"]["hypothesis_id"] == "H1"
    assert context["relevant_evidence"][0]["direction"] == "contradicting"
    assert context["relevant_observations"][0]["observation_id"] == "O1"
    assert context["diagnosis_state"]["remaining_tool_budget"] == 6
    assert "excerpt" not in context["relevant_observations"][0]


def test_h2_context_contains_rejected_h1_and_rejection_knowledge() -> None:
    state = DiagnosisStateMachine(tool_call_limit=8)
    state.begin_hypothesis_formation()
    state.form_initial_hypothesis(FormHypothesisDecision(hypothesis=proposal(1)))
    current, _, _ = diagnostic_records()
    state.begin_experiment(current)
    observation = state.record_observation(
        ToolResult(
            tool_result_id="T1",
            experiment_id="X1",
            hypothesis_id="H1",
            tool_name="read_code",
            status="success",
            output="1: value = 1\n",
            artifact_ref="tool-results/T1.txt",
            duration_ms=1,
        )
    )
    evidence = state.record_evidence(
        UpdateEvidenceDecision(
            hypothesis_id="H1",
            observation_ref="O1",
            direction="contradicting",
            explanation="The observed implementation contradicts H1.",
        )
    )
    state.apply_hypothesis_assessment(
        HypothesisAssessmentDecision(
            outcome="falsified",
            evidence_refs=("E1",),
            rationale="The registered Evidence falsifies H1.",
        )
    )

    context = ContextBuilder().build_form_hypothesis(
        task_context(),
        state,
        observations=[observation],
        evidence=[evidence],
    )

    assert context["decision_type"] == "reformulate_hypothesis"
    assert context["diagnosis_state"]["hypothesis_history"][0]["status"] == "rejected"
    assert context["reformulation_knowledge"]["evidence"][0]["evidence_id"] == "E1"
    observations = context["reformulation_knowledge"]["observations"]
    assert observations[0]["observation_id"] == "O1"
    assert context["diagnosis_state"]["remaining_hypothesis_budget"] == 2
    assert context["diagnosis_state"]["remaining_tool_budget"] == 7
    assert "x" * 1_000 not in str(context)


def test_validation_context_requires_supported_hypothesis() -> None:
    state = state_with_h1()
    state.transition_hypothesis("H1", "supported")
    _, observation, evidence = diagnostic_records()

    context = ContextBuilder().build_validation(
        task_context(), state, observations=[observation], evidence=[evidence]
    )

    assert context["supported_hypothesis"]["hypothesis_id"] == "H1"
    assert context["relevant_evidence"][0]["evidence_id"] == "E1"
    assert context["relevant_observations"][0]["artifact_ref"] == "tool-results/O1.txt"
    assert len(context["relevant_observations"][0]["excerpt"]) == 2_000
    assert context["relevant_observations"][0]["truncated"] is True


def test_resolve_task_context_reads_bounded_ci_artifact_from_task_directory(
    tmp_path: Path,
) -> None:
    task_dir = tmp_path / "task"
    (task_dir / "ci").mkdir(parents=True)
    (task_dir / "ci" / "failure.log").write_text("real failure\n" * 500)

    task = resolve_task_context(manifest(), task_dir, ci_excerpt_limit=120)

    assert len(task.ci_failure_excerpt) == 120
    assert task.ci_failure_excerpt.startswith("real failure")
    assert task.ci_failure_artifact == "ci/failure.log"


def test_resolve_task_context_rejects_ci_artifact_path_escape(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside.log"
    outside.write_text("secret")
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    unsafe = manifest().model_copy(update={"ci_log": "../outside.log"})

    with pytest.raises(ValueError, match="task directory"):
        resolve_task_context(unsafe, task_dir)
