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
    Hypothesis,
    HypothesisAssessmentDecision,
    HypothesisProposal,
    Observation,
    ReformulateHypothesisDecision,
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


def test_evidence_basis_projection_preserves_declared_order_and_selectivity() -> None:
    hypothesis = Hypothesis(
        hypothesis_id="H3",
        mechanism="A replacement mechanism.",
        falsification_criterion="A discriminating observation would reject it.",
        location_description="src/module.py",
        evidence_basis=("E2", "E1"),
    )
    observations = [
        Observation(
            observation_id=f"O{index}",
            experiment_id=f"X{index}",
            hypothesis_id="H1",
            tool_result_ref=f"T{index}",
            source="read_code",
            summary=f"observation {index}",
            artifact_ref=f"tool-results/T{index}.txt",
            excerpt=f"excerpt {index}",
        )
        for index in range(1, 4)
    ]
    evidence = [
        Evidence(
            evidence_id=f"E{index}",
            hypothesis_id="H1",
            observation_ref=f"O{index}",
            provenance=f"read_code:tool-results/T{index}.txt",
            direction="contradicting",
            explanation=f"evidence {index}",
        )
        for index in (1, 2, 3)
    ]

    projection = ContextBuilder()._evidence_basis_knowledge(
        hypothesis,
        evidence,
        observations,
    )

    assert [item["evidence_id"] for item in projection["evidence"]] == ["E2", "E1"]
    assert [item["observation_id"] for item in projection["observations"]] == [
        "O2",
        "O1",
    ]


def test_h1_context_contains_task_and_budgets_without_history() -> None:
    state = DiagnosisStateMachine()

    context = ContextBuilder().build_form_hypothesis(task_context(), state)

    assert context["decision_type"] == "form_hypothesis"
    assert context["diagnosis_state"]["hypothesis_history"] == []
    assert context["diagnosis_state"]["remaining_hypothesis_budget"] == 3
    assert context["diagnosis_state"]["remaining_tool_budget"] == 8
    assert context["diagnosis_state"]["used_experiment_budget"] == 0
    assert context["diagnosis_state"]["remaining_experiment_budget"] == 3
    assert context["task_context"]["ci_failure"]["excerpt"].startswith("AssertionError")
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
                "observation_capabilities": ["Return bounded source lines."],
                "limitations": ["Does not execute code."],
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
    assert context["diagnosis_state"]["remaining_experiment_budget"] == 3
    assert context["available_tools"][0]["name"] == "read_code"
    assert context["available_tools"][0]["observation_capabilities"] == [
        "Return bounded source lines."
    ]
    assert context["available_tools"][0]["limitations"] == [
        "Does not execute code."
    ]


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
    assert context["evidence_basis_knowledge"] == {
        "evidence": [],
        "observations": [],
    }


def test_assessment_context_contains_only_active_hypothesis_knowledge() -> None:
    state = state_with_h1()
    _, observation, evidence = diagnostic_records()

    context = ContextBuilder().build_assess_hypothesis(
        task_context(),
        state,
        available_tools=[
            {
                "name": "read_code",
                "observation_capabilities": ["Return bounded source lines."],
                "limitations": ["Does not execute code."],
            }
        ],
        observations=[observation],
        evidence=[evidence],
        used_tool_calls=2,
    )

    assert context["decision_type"] == "assess_hypothesis"
    assert (
        context["evidence_direction_contract"]["reference"]
        == "active_hypothesis.mechanism"
    )
    assert context["assessment_requirements"]["sufficiently_supported"] == "supporting"
    assert context["active_hypothesis"]["hypothesis_id"] == "H1"
    assert context["relevant_evidence"][0]["direction"] == "contradicting"
    assert context["relevant_observations"][0]["observation_id"] == "O1"
    assert context["diagnosis_state"]["remaining_tool_budget"] == 6
    assert context["available_tools"][0]["name"] == "read_code"
    assert len(context["relevant_observations"][0]["excerpt"]) == 2_000
    assert context["evidence_basis_knowledge"] == {
        "evidence": [],
        "observations": [],
    }


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
            output="x" * 4_000,
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
        available_tools=[
            {
                "name": "read_code",
                "observation_capabilities": ["Return bounded source lines."],
                "limitations": ["Does not execute code."],
            }
        ],
    )

    assert context["decision_type"] == "reformulate_hypothesis"
    assert context["diagnosis_state"]["hypothesis_history"][0]["status"] == "rejected"
    assert context["reformulation_knowledge"]["evidence"][0]["evidence_id"] == "E1"
    observations = context["reformulation_knowledge"]["observations"]
    assert observations[0]["observation_id"] == "O1"
    assert context["diagnosis_state"]["remaining_hypothesis_budget"] == 2
    assert context["diagnosis_state"]["remaining_tool_budget"] == 7
    assert context["available_tools"][0]["name"] == "read_code"
    assert "x" * 1_000 not in str(context)
    state.begin_hypothesis_formation()
    state.reformulate_hypothesis(
        ReformulateHypothesisDecision(hypothesis=proposal(2), evidence_refs=("E1",))
    )
    selected = ContextBuilder().build_select_experiment(
        task_context(),
        state,
        available_tools=[],
        experiments=[current],
        observations=[observation],
        evidence=[evidence],
        used_tool_calls=1,
    )
    assert selected["evidence_basis_knowledge"]["evidence"][0]["evidence_id"] == "E1"
    assert (
        len(selected["evidence_basis_knowledge"]["observations"][0]["excerpt"])
        == 2_000
    )
    assert (
        selected["evidence_basis_knowledge"]["observations"][0]["observation_id"]
        == "O1"
    )
    assert selected["evidence_basis_knowledge"]["observations"][0]["truncated"]

    h2_experiment = Experiment(
        experiment_id="X2",
        hypothesis_id="H2",
        purpose="Inspect the dependency identified by E1.",
        expected_observation="The dependency preserves the original argument.",
        falsification_relevance="The call relationship distinguishes H2.",
        tool_name="read_code",
        arguments={"path": "src/helper.py", "start_line": 1, "end_line": 40},
    )
    h2_observation = Observation(
        observation_id="O2",
        experiment_id="X2",
        hypothesis_id="H2",
        tool_result_ref="T2",
        source="read_code",
        summary="The helper transforms its second argument.",
        artifact_ref="tool-results/T2.txt",
        excerpt="helper code",
    )
    h2_evidence = Evidence(
        evidence_id="E2",
        hypothesis_id="H2",
        observation_ref="O2",
        provenance="read_code:tool-results/T2.txt",
        direction="supporting",
        explanation="The helper behavior supports H2.",
    )

    updated = ContextBuilder(observation_excerpt_limit=20).build_update_evidence(
        task_context(),
        state,
        experiment=h2_experiment,
        latest_observation=h2_observation,
        evidence=[evidence, h2_evidence],
    )
    assert [
        item["evidence_id"]
        for item in updated["evidence_basis_knowledge"]["evidence"]
    ] == ["E1"]
    assert [
        item["observation_id"]
        for item in updated["evidence_basis_knowledge"]["observations"]
    ] == ["O1"]
    assert len(updated["evidence_basis_knowledge"]["observations"][0]["excerpt"]) == 20
    assert updated["evidence_basis_knowledge"]["observations"][0]["truncated"]
    assert [
        item["evidence_id"] for item in updated["existing_relevant_evidence"]
    ] == ["E2"]

    assessed = ContextBuilder(observation_excerpt_limit=20).build_assess_hypothesis(
        task_context(),
        state,
        available_tools=[],
        observations=[observation, h2_observation],
        evidence=[evidence, h2_evidence],
        used_tool_calls=2,
    )
    assert [
        item["evidence_id"]
        for item in assessed["evidence_basis_knowledge"]["evidence"]
    ] == ["E1"]
    assert [item["evidence_id"] for item in assessed["relevant_evidence"]] == [
        "E2"
    ]

    state.transition_hypothesis("H2", "supported")
    validation = ContextBuilder(
        observation_excerpt_limit=20
    ).build_validation(
        task_context(),
        state,
        observations=[observation, h2_observation],
        evidence=[evidence, h2_evidence],
    )
    assert [
        item["evidence_id"]
        for item in validation["evidence_basis_knowledge"]["evidence"]
    ] == ["E1"]
    assert [item["evidence_id"] for item in validation["relevant_evidence"]] == [
        "E2"
    ]


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
    assert context["evidence_basis_knowledge"] == {
        "evidence": [],
        "observations": [],
    }


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
