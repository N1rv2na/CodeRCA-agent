from __future__ import annotations

import pytest

from coderca.contracts import (
    DiagnosisStage,
    Evidence,
    Experiment,
    FormHypothesisDecision,
    Hypothesis,
    HypothesisAssessmentDecision,
    HypothesisProposal,
)
from coderca.diagnosis_state import DiagnosisStateMachine, InvalidDiagnosisTransition


def proposal(index: int, *, evidence_basis: tuple[str, ...] = ()) -> HypothesisProposal:
    return HypothesisProposal(
        root_symbol=f"package.module.function_{index}",
        location_description=None,
        mechanism=f"Branch {index} mishandles the failing input.",
        falsification_criterion=f"Reading branch {index} shows the input is preserved.",
        evidence_basis=evidence_basis,
    )


def form_next(
    state: DiagnosisStateMachine,
    index: int,
    *,
    evidence_basis: tuple[str, ...] = (),
) -> Hypothesis:
    state.begin_hypothesis_formation()
    return state.form_hypothesis(
        FormHypothesisDecision(
            hypothesis=proposal(index, evidence_basis=evidence_basis)
        )
    )


def test_first_formation_creates_only_program_identified_h1() -> None:
    state = DiagnosisStateMachine()

    hypothesis = form_next(state, 1)

    assert hypothesis.hypothesis_id == "H1"
    assert hypothesis.status == "proposed"
    assert state.hypothesis_history == (hypothesis,)
    assert state.active_hypothesis == hypothesis
    assert state.remaining_hypothesis_budget == 2
    assert state.stage is DiagnosisStage.DIAGNOSING


def test_active_hypothesis_blocks_reformulation() -> None:
    state = DiagnosisStateMachine()
    h1 = form_next(state, 1)

    with pytest.raises(InvalidDiagnosisTransition, match="active Hypothesis H1"):
        state.begin_hypothesis_formation()

    assert state.hypothesis_history == (h1,)


def test_rejected_h1_allows_materially_new_h2_with_evidence_basis() -> None:
    state = DiagnosisStateMachine()
    form_next(state, 1)
    state.transition_hypothesis("H1", "testing")
    rejected_h1 = state.transition_hypothesis("H1", "rejected")

    h2 = form_next(state, 2, evidence_basis=("E1",))

    assert rejected_h1.status == "rejected"
    assert h2.hypothesis_id == "H2"
    assert h2.evidence_basis == ("E1",)
    assert [item.hypothesis_id for item in state.hypothesis_history] == ["H1", "H2"]
    assert state.active_hypothesis == h2


def test_reformulation_requires_evidence_basis() -> None:
    state = DiagnosisStateMachine()
    form_next(state, 1)
    state.transition_hypothesis("H1", "rejected")

    state.begin_hypothesis_formation()
    with pytest.raises(InvalidDiagnosisTransition, match="evidence basis"):
        state.form_hypothesis(FormHypothesisDecision(hypothesis=proposal(2)))


def test_rejected_hypothesis_is_immutable_and_cannot_revive() -> None:
    state = DiagnosisStateMachine()
    original_h1 = form_next(state, 1)
    rejected_h1 = state.transition_hypothesis("H1", "rejected")

    with pytest.raises(InvalidDiagnosisTransition):
        state.transition_hypothesis("H1", "testing")

    assert original_h1.mechanism == rejected_h1.mechanism
    assert state.hypothesis_history[0] == rejected_h1


def test_h2_rejected_allows_h3_but_h3_end_exhausts_budget() -> None:
    state = DiagnosisStateMachine()
    form_next(state, 1)
    state.transition_hypothesis("H1", "rejected")
    form_next(state, 2, evidence_basis=("E1",))
    state.transition_hypothesis("H2", "rejected")

    h3 = form_next(state, 3, evidence_basis=("E2",))
    state.transition_hypothesis("H3", "inconclusive")

    assert h3.hypothesis_id == "H3"
    assert state.remaining_hypothesis_budget == 0
    assert state.hypothesis_budget_exhausted is True
    assert [item.hypothesis_id for item in state.hypothesis_history] == [
        "H1",
        "H2",
        "H3",
    ]
    with pytest.raises(InvalidDiagnosisTransition, match="budget exhausted"):
        state.begin_hypothesis_formation()


def test_supported_hypothesis_cannot_be_reformulated() -> None:
    state = DiagnosisStateMachine()
    form_next(state, 1)
    state.transition_hypothesis("H1", "testing")
    state.transition_hypothesis("H1", "supported")

    with pytest.raises(InvalidDiagnosisTransition, match="supported"):
        state.begin_hypothesis_formation()


def test_state_machine_allows_exactly_one_schema_correction_per_formation() -> None:
    state = DiagnosisStateMachine()
    state.begin_hypothesis_formation()

    state.authorize_schema_correction()

    assert state.schema_corrections_used == 1
    with pytest.raises(InvalidDiagnosisTransition, match="already been used"):
        state.authorize_schema_correction()


def test_terminal_stage_rejects_further_diagnosis_actions() -> None:
    state = DiagnosisStateMachine()
    state.transition_to(DiagnosisStage.FINALIZING)

    with pytest.raises(InvalidDiagnosisTransition):
        state.begin_hypothesis_formation()


def experiment(hypothesis_id: str) -> Experiment:
    return Experiment(
        experiment_id="X1",
        hypothesis_id=hypothesis_id,
        purpose="Try to falsify the active mechanism.",
        expected_observation="The branch preserves the failing value.",
        falsification_relevance="That result contradicts the mechanism.",
        tool_name="read_code",
        arguments={"path": "package/module.py"},
    )


def contradicting_evidence(hypothesis_id: str) -> Evidence:
    return Evidence(
        evidence_id="E1",
        hypothesis_id=hypothesis_id,
        observation_ref="O1",
        provenance="read_code:tool-results/O1.txt",
        direction="contradicting",
        explanation="The observed branch contradicts the mechanism.",
    )


def test_experiment_must_bind_the_current_active_hypothesis() -> None:
    state = DiagnosisStateMachine()
    form_next(state, 1)

    state.authorize_experiment(experiment("H1"))

    with pytest.raises(InvalidDiagnosisTransition, match="Active Hypothesis H1"):
        state.authorize_experiment(experiment("H2"))


def test_rejected_hypothesis_cannot_receive_an_experiment() -> None:
    state = DiagnosisStateMachine()
    form_next(state, 1)
    state.transition_hypothesis("H1", "rejected")

    with pytest.raises(InvalidDiagnosisTransition, match="requires one Active"):
        state.authorize_experiment(experiment("H1"))


def test_contradicting_evidence_allows_program_owned_rejection() -> None:
    state = DiagnosisStateMachine()
    form_next(state, 1)
    assessment = HypothesisAssessmentDecision(
        outcome="falsified",
        evidence_refs=("E1",),
        rationale="The observed code contradicts the proposed mechanism.",
    )

    rejected = state.apply_hypothesis_assessment(
        assessment, evidence=[contradicting_evidence("H1")]
    )

    assert rejected.hypothesis_id == "H1"
    assert rejected.status == "rejected"
    assert state.active_hypothesis is None


def test_falsified_assessment_without_contradicting_evidence_is_rejected() -> None:
    state = DiagnosisStateMachine()
    form_next(state, 1)
    assessment = HypothesisAssessmentDecision(
        outcome="falsified",
        evidence_refs=("E1",),
        rationale="Unsupported rejection attempt.",
    )
    supporting = contradicting_evidence("H1").model_copy(
        update={"direction": "supporting"}
    )

    with pytest.raises(InvalidDiagnosisTransition, match="Contradicting Evidence"):
        state.apply_hypothesis_assessment(assessment, evidence=[supporting])


def test_continue_testing_assessment_keeps_testing_hypothesis_active() -> None:
    state = DiagnosisStateMachine()
    form_next(state, 1)
    supporting = contradicting_evidence("H1").model_copy(
        update={"direction": "supporting"}
    )
    assessment = HypothesisAssessmentDecision(
        outcome="continue_testing",
        evidence_refs=("E1",),
        rationale="More discriminating evidence is needed.",
    )

    first = state.apply_hypothesis_assessment(assessment, evidence=[supporting])
    second = state.apply_hypothesis_assessment(assessment, evidence=[supporting])

    assert first.status == "testing"
    assert second.status == "testing"
    assert state.active_hypothesis == second
