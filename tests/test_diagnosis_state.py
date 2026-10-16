from __future__ import annotations

import pytest
from pydantic import ValidationError

from coderca.contracts import DiagnosisStage, FormHypothesesDecision, HypothesisProposal
from coderca.diagnosis_state import (
    DiagnosisStateMachine,
    InvalidDiagnosisTransition,
)


def proposal(index: int) -> HypothesisProposal:
    return HypothesisProposal(
        root_symbol=f"package.module.function_{index}",
        location_description=None,
        mechanism=f"Branch {index} mishandles the failing input.",
        falsification_criterion=f"Reading branch {index} shows the input is preserved.",
    )


@pytest.mark.parametrize("count", [1, 3])
def test_state_machine_forms_bounded_hypotheses_with_stable_ordered_ids(
    count: int,
) -> None:
    state = DiagnosisStateMachine()
    state.transition_to(DiagnosisStage.FORMING_HYPOTHESES)
    decision = FormHypothesesDecision(
        hypotheses=[proposal(index) for index in range(1, count + 1)]
    )

    hypotheses = state.form_initial_hypotheses(decision)

    assert state.stage is DiagnosisStage.DIAGNOSING
    assert [item.hypothesis_id for item in hypotheses] == [
        f"H{index}" for index in range(1, count + 1)
    ]
    assert [item.root_symbol for item in hypotheses] == [
        f"package.module.function_{index}" for index in range(1, count + 1)
    ]
    assert all(item.status == "proposed" for item in hypotheses)
    assert state.hypotheses == hypotheses


@pytest.mark.parametrize("count", [0, 4])
def test_formation_contract_rejects_zero_or_more_than_three_hypotheses(
    count: int,
) -> None:
    with pytest.raises(ValidationError):
        FormHypothesesDecision(
            hypotheses=[proposal(index) for index in range(1, count + 1)]
        )


def test_hypothesis_requires_a_root_symbol_or_location_description() -> None:
    with pytest.raises(ValidationError):
        HypothesisProposal(
            root_symbol=None,
            location_description=None,
            mechanism="A falsifiable mechanism.",
            falsification_criterion="A contrary code observation.",
        )


def test_initial_hypotheses_cannot_be_added_or_replaced_after_formation() -> None:
    state = DiagnosisStateMachine()
    state.transition_to(DiagnosisStage.FORMING_HYPOTHESES)
    original = state.form_initial_hypotheses(
        FormHypothesesDecision(hypotheses=[proposal(1)])
    )

    with pytest.raises(InvalidDiagnosisTransition):
        state.form_initial_hypotheses(
            FormHypothesesDecision(hypotheses=[proposal(1), proposal(2)])
        )

    assert state.hypotheses == original


def test_state_machine_allows_exactly_one_schema_correction_while_forming() -> None:
    state = DiagnosisStateMachine()
    state.transition_to(DiagnosisStage.FORMING_HYPOTHESES)

    state.authorize_schema_correction()

    assert state.schema_corrections_used == 1
    with pytest.raises(InvalidDiagnosisTransition, match="already been used"):
        state.authorize_schema_correction()


def test_state_machine_rejects_schema_correction_outside_formation_stage() -> None:
    state = DiagnosisStateMachine()

    with pytest.raises(InvalidDiagnosisTransition, match="forming_hypotheses"):
        state.authorize_schema_correction()


def test_rejected_hypothesis_cannot_be_revived_or_change_initial_membership() -> None:
    state = DiagnosisStateMachine()
    state.transition_to(DiagnosisStage.FORMING_HYPOTHESES)
    state.form_initial_hypotheses(
        FormHypothesesDecision(hypotheses=[proposal(1), proposal(2)])
    )

    rejected = state.transition_hypothesis("H1", "rejected")

    assert rejected.status == "rejected"
    assert [item.hypothesis_id for item in state.hypotheses] == ["H1", "H2"]
    with pytest.raises(InvalidDiagnosisTransition):
        state.transition_hypothesis("H1", "testing")
    with pytest.raises(InvalidDiagnosisTransition):
        state.transition_hypothesis("H3", "testing")


_ALLOWED_STAGE_PAIRS = {
    (DiagnosisStage.PREPARING, DiagnosisStage.FORMING_HYPOTHESES),
    (DiagnosisStage.PREPARING, DiagnosisStage.FINALIZING),
    (DiagnosisStage.FORMING_HYPOTHESES, DiagnosisStage.FINALIZING),
    (DiagnosisStage.DIAGNOSING, DiagnosisStage.FINALIZING),
}
_ALL_STAGE_PAIRS = [
    (source, target, (source, target) in _ALLOWED_STAGE_PAIRS)
    for source in DiagnosisStage
    for target in DiagnosisStage
]


@pytest.mark.parametrize(("source", "target", "allowed"), _ALL_STAGE_PAIRS)
def test_state_machine_enforces_complete_lifecycle_transition_table(
    source: DiagnosisStage, target: DiagnosisStage, allowed: bool
) -> None:
    state = DiagnosisStateMachine(stage=source)

    if allowed:
        state.transition_to(target)
        assert state.stage is target
    else:
        with pytest.raises(InvalidDiagnosisTransition):
            state.transition_to(target)
        assert state.stage is source
