from __future__ import annotations

import pytest
from pydantic import ValidationError

from coderca.contracts import (
    DiagnosisStage,
    Evidence,
    EvidenceDirection,
    Experiment,
    FormHypothesisDecision,
    Hypothesis,
    HypothesisAssessmentDecision,
    HypothesisAssessmentOutcome,
    HypothesisProposal,
    PatchValidationAction,
    ReformulateHypothesisDecision,
    SelectExperimentDecision,
    ToolResult,
    UpdateEvidenceDecision,
)
from coderca.diagnosis_state import DiagnosisStateMachine, InvalidDiagnosisTransition


def proposal(index: int) -> HypothesisProposal:
    return HypothesisProposal(
        root_symbol=f"package.module.function_{index}",
        location_description=None,
        mechanism=f"Branch {index} mishandles the failing input.",
        falsification_criterion=f"Reading branch {index} shows the input is preserved.",
    )


def form_h1(state: DiagnosisStateMachine) -> Hypothesis:
    state.begin_hypothesis_formation()
    return state.form_initial_hypothesis(FormHypothesisDecision(hypothesis=proposal(1)))


def validation_action(hypothesis_id: str = "H1") -> PatchValidationAction:
    return PatchValidationAction(
        validation_action_id="V1",
        hypothesis_id=hypothesis_id,
        purpose="Apply one candidate patch and run Public Validation.",
        tool_name="apply_patch",
        arguments={"target_path": "src/module.py", "unified_diff": "diff"},
    )


def reformulate(
    state: DiagnosisStateMachine,
    index: int,
    *,
    evidence_refs: tuple[str, ...],
) -> Hypothesis:
    state.begin_hypothesis_formation()
    return state.reformulate_hypothesis(
        ReformulateHypothesisDecision(
            hypothesis=proposal(index), evidence_refs=evidence_refs
        )
    )


def register_evidence(
    state: DiagnosisStateMachine,
    *,
    direction: EvidenceDirection = "contradicting",
) -> Evidence:
    active = state.active_hypothesis
    assert active is not None
    sequence = len(state.experiments) + 1
    current = experiment(active.hypothesis_id).model_copy(
        update={"experiment_id": f"X{sequence}"}
    )
    state.begin_experiment(current)
    observation = state.record_observation(
        successful_tool_result(
            experiment_id=current.experiment_id,
            hypothesis_id=active.hypothesis_id,
        )
    )
    return state.record_evidence(
        UpdateEvidenceDecision(
            hypothesis_id=active.hypothesis_id,
            observation_ref=observation.observation_id,
            direction=direction,
            explanation="The Observation changes the diagnosis direction.",
        )
    )


def assess_active(
    state: DiagnosisStateMachine,
    *,
    outcome: HypothesisAssessmentOutcome = "falsified",
    direction: EvidenceDirection = "contradicting",
) -> Evidence:
    evidence = register_evidence(state, direction=direction)
    state.apply_hypothesis_assessment(
        HypothesisAssessmentDecision(
            outcome=outcome,
            evidence_refs=(evidence.evidence_id,),
            rationale="The registered Evidence determines the lifecycle outcome.",
        )
    )
    return evidence


def test_initial_formation_contract_rejects_free_text_evidence_basis() -> None:
    schema = FormHypothesisDecision.model_json_schema()
    payload = {
        "hypothesis": {
            **proposal(1).model_dump(mode="json"),
            "evidence_basis": ["The write boundary suggests this file."],
        }
    }

    with pytest.raises(ValidationError, match="evidence_basis"):
        FormHypothesisDecision.model_validate(payload)
    assert "evidence_basis" not in str(schema)


def test_reformulation_contract_requires_unique_evidence_ids() -> None:
    with pytest.raises(ValidationError, match="at least 1"):
        ReformulateHypothesisDecision(hypothesis=proposal(2), evidence_refs=())

    with pytest.raises(ValidationError, match="unique"):
        ReformulateHypothesisDecision(
            hypothesis=proposal(2), evidence_refs=("E1", "E1")
        )


def test_first_formation_creates_only_program_identified_h1() -> None:
    state = DiagnosisStateMachine()

    hypothesis = form_h1(state)

    assert hypothesis.hypothesis_id == "H1"
    assert hypothesis.status == "proposed"
    assert hypothesis.evidence_basis == ()
    assert state.hypothesis_history == (hypothesis,)
    assert state.active_hypothesis == hypothesis
    assert state.remaining_hypothesis_budget == 2
    assert state.stage is DiagnosisStage.DIAGNOSING


def test_active_hypothesis_blocks_reformulation() -> None:
    state = DiagnosisStateMachine()
    h1 = form_h1(state)

    with pytest.raises(InvalidDiagnosisTransition, match="active Hypothesis H1"):
        state.begin_hypothesis_formation()

    assert state.hypothesis_history == (h1,)


def test_rejected_h1_allows_materially_new_h2_with_evidence_basis() -> None:
    state = DiagnosisStateMachine()
    form_h1(state)
    evidence = assess_active(state)
    rejected_h1 = state.hypothesis_history[0]

    h2 = reformulate(state, 2, evidence_refs=(evidence.evidence_id,))

    assert rejected_h1.status == "rejected"
    assert h2.hypothesis_id == "H2"
    assert h2.evidence_basis == ("E1",)
    assert [item.hypothesis_id for item in state.hypothesis_history] == ["H1", "H2"]
    assert state.active_hypothesis == h2


def test_reformulation_rejects_unknown_evidence_id() -> None:
    state = DiagnosisStateMachine()
    form_h1(state)
    state.transition_hypothesis("H1", "rejected")

    state.begin_hypothesis_formation()
    decision = ReformulateHypothesisDecision(
        hypothesis=proposal(2), evidence_refs=("E-unknown",)
    )
    with pytest.raises(InvalidDiagnosisTransition, match="unknown Evidence"):
        state.reformulate_hypothesis(decision)


def test_reformulation_cannot_accept_caller_supplied_evidence() -> None:
    state = DiagnosisStateMachine()
    form_h1(state)
    state.transition_hypothesis("H1", "rejected")
    state.begin_hypothesis_formation()
    decision = ReformulateHypothesisDecision(
        hypothesis=proposal(2), evidence_refs=("E9",)
    )
    with pytest.raises(TypeError, match="evidence"):
        state.reformulate_hypothesis(  # type: ignore[call-arg]
            decision,
            evidence=[contradicting_evidence("H9")],
        )


def test_reformulation_rejects_a_rewording_free_exact_mechanism_repeat() -> None:
    state = DiagnosisStateMachine()
    h1 = form_h1(state)
    assess_active(state)
    state.begin_hypothesis_formation()
    repeated = ReformulateHypothesisDecision(
        hypothesis=proposal(2).model_copy(update={"mechanism": f"  {h1.mechanism}  "}),
        evidence_refs=("E1",),
    )

    with pytest.raises(InvalidDiagnosisTransition, match="materially different"):
        state.reformulate_hypothesis(repeated)


def test_rejected_hypothesis_is_immutable_and_cannot_revive() -> None:
    state = DiagnosisStateMachine()
    original_h1 = form_h1(state)
    rejected_h1 = state.transition_hypothesis("H1", "rejected")

    with pytest.raises(InvalidDiagnosisTransition):
        state.transition_hypothesis("H1", "testing")

    assert original_h1.mechanism == rejected_h1.mechanism
    assert state.hypothesis_history[0] == rejected_h1


def test_h2_rejected_allows_h3_but_h3_end_exhausts_budget() -> None:
    state = DiagnosisStateMachine()
    form_h1(state)
    assess_active(state)
    reformulate(state, 2, evidence_refs=("E1",))
    assess_active(state)

    h3 = reformulate(
        state,
        3,
        evidence_refs=("E1", "E2"),
    )
    state.transition_hypothesis("H3", "inconclusive")

    assert h3.hypothesis_id == "H3"
    assert h3.evidence_basis == ("E1", "E2")
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
    form_h1(state)
    state.transition_hypothesis("H1", "testing")
    state.transition_hypothesis("H1", "supported")

    with pytest.raises(InvalidDiagnosisTransition, match="supported"):
        state.begin_hypothesis_formation()


@pytest.mark.parametrize(
    "status", ["proposed", "testing", "rejected", "inconclusive"]
)
def test_only_supported_hypothesis_can_begin_validation(status: str) -> None:
    state = DiagnosisStateMachine()
    form_h1(state)
    if status != "proposed":
        state.transition_hypothesis("H1", status)  # type: ignore[arg-type]

    with pytest.raises(InvalidDiagnosisTransition, match="supported"):
        state.begin_validation(validation_action())


def test_supported_hypothesis_enters_validation_once() -> None:
    state = DiagnosisStateMachine()
    form_h1(state)
    state.transition_hypothesis("H1", "supported")

    action = validation_action()
    state.begin_validation(action)

    assert state.stage is DiagnosisStage.VALIDATING
    assert state.used_tool_calls == 1
    assert state.validation_actions == (action,)
    with pytest.raises(InvalidDiagnosisTransition):
        state.begin_validation(action)


def test_patch_validation_is_rejected_when_tool_budget_is_exhausted() -> None:
    state = DiagnosisStateMachine(tool_call_limit=1)
    form_h1(state)
    evidence = register_evidence(state, direction="supporting")
    state.apply_hypothesis_assessment(
        HypothesisAssessmentDecision(
            outcome="sufficiently_supported",
            evidence_refs=(evidence.evidence_id,),
            rationale="The registered Evidence supports H1.",
        )
    )

    with pytest.raises(InvalidDiagnosisTransition, match="Tool budget exhausted"):
        state.begin_validation(validation_action())


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
    form_h1(state)

    state.authorize_experiment(experiment("H1"))

    with pytest.raises(InvalidDiagnosisTransition, match="Active Hypothesis H1"):
        state.authorize_experiment(experiment("H2"))


@pytest.mark.parametrize(
    "missing_field",
    ["purpose", "expected_observation", "falsification_relevance"],
)
def test_experiment_decision_requires_falsification_metadata_before_execution(
    missing_field: str,
) -> None:
    payload: dict[str, object] = {
        "hypothesis_id": "H1",
        "purpose": "Inspect the relevant branch.",
        "expected_observation": "The branch preserves explicit false.",
        "falsification_relevance": "That result contradicts H1.",
        "tool_name": "read_code",
        "arguments": {"path": "src/module.py"},
    }
    del payload[missing_field]

    with pytest.raises(ValidationError, match=missing_field):
        SelectExperimentDecision.model_validate(payload)


def test_rejected_hypothesis_cannot_receive_an_experiment() -> None:
    state = DiagnosisStateMachine()
    form_h1(state)
    state.transition_hypothesis("H1", "rejected")

    with pytest.raises(InvalidDiagnosisTransition, match="requires one Active"):
        state.authorize_experiment(experiment("H1"))


def test_contradicting_evidence_allows_program_owned_rejection() -> None:
    state = DiagnosisStateMachine()
    form_h1(state)
    assessment = HypothesisAssessmentDecision(
        outcome="falsified",
        evidence_refs=("E1",),
        rationale="The observed code contradicts the proposed mechanism.",
    )

    registered = register_evidence(state)
    assert registered.evidence_id == "E1"
    rejected = state.apply_hypothesis_assessment(assessment)

    assert rejected.hypothesis_id == "H1"
    assert rejected.status == "rejected"
    assert state.active_hypothesis is None


def test_falsified_assessment_without_contradicting_evidence_is_rejected() -> None:
    state = DiagnosisStateMachine()
    form_h1(state)
    assessment = HypothesisAssessmentDecision(
        outcome="falsified",
        evidence_refs=("E1",),
        rationale="Unsupported rejection attempt.",
    )
    register_evidence(state, direction="supporting")

    with pytest.raises(InvalidDiagnosisTransition, match="Contradicting Evidence"):
        state.apply_hypothesis_assessment(assessment)
    assert state.stage is DiagnosisStage.UPDATING_EVIDENCE
    assert state.active_hypothesis is not None


def test_assessment_semantic_validation_is_non_mutating_and_reports_allowed_evidence(
) -> None:
    state = DiagnosisStateMachine()
    form_h1(state)
    register_evidence(state, direction="supporting")
    assessment = HypothesisAssessmentDecision(
        outcome="sufficiently_supported",
        evidence_refs=("E1", "O1"),
        rationale="E1 supports H1, while O1 is mistakenly cited as Evidence.",
    )

    with pytest.raises(ValueError, match="unknown Evidence") as raised:
        state.validate_hypothesis_assessment(assessment)

    errors = getattr(raised.value, "validation_errors")
    assert errors[0]["loc"] == ["evidence_refs", 1]
    assert errors[0]["input"] == "O1"
    assert errors[0]["allowed_evidence_ids"] == ["E1"]
    assert state.stage is DiagnosisStage.UPDATING_EVIDENCE
    assert state.active_hypothesis is not None
    assert state.active_hypothesis.status == "proposed"


def test_assessment_semantic_validation_rejects_incompatible_evidence_direction(
) -> None:
    state = DiagnosisStateMachine()
    form_h1(state)
    register_evidence(state, direction="supporting")
    assessment = HypothesisAssessmentDecision(
        outcome="falsified",
        evidence_refs=("E1",),
        rationale="An invalid attempt to falsify H1 with Supporting Evidence.",
    )

    with pytest.raises(ValueError, match="Contradicting Evidence") as raised:
        state.validate_hypothesis_assessment(assessment)

    errors = getattr(raised.value, "validation_errors")
    assert errors[0]["loc"] == ["evidence_refs"]
    assert errors[0]["type"] == "incompatible_evidence_direction"
    assert state.stage is DiagnosisStage.UPDATING_EVIDENCE
    assert state.active_hypothesis is not None


def test_continue_testing_assessment_keeps_testing_hypothesis_active() -> None:
    state = DiagnosisStateMachine()
    form_h1(state)
    register_evidence(state, direction="supporting")
    assessment = HypothesisAssessmentDecision(
        outcome="continue_testing",
        evidence_refs=("E1",),
        rationale="More discriminating evidence is needed.",
    )

    first = state.apply_hypothesis_assessment(assessment)

    assert first.status == "testing"
    assert state.active_hypothesis == first
    with pytest.raises(InvalidDiagnosisTransition, match="updating_evidence"):
        state.apply_hypothesis_assessment(assessment)


def successful_tool_result(
    experiment_id: str = "X1", hypothesis_id: str = "H1"
) -> ToolResult:
    return ToolResult(
        tool_result_id="T1",
        experiment_id=experiment_id,
        hypothesis_id=hypothesis_id,
        tool_name="read_code",
        status="success",
        output="1: value = configured if configured is not None else default\n",
        artifact_ref="tool-results/T1.txt",
        duration_ms=1,
    )


def test_tool_result_observation_and_evidence_are_program_linked() -> None:
    state = DiagnosisStateMachine(tool_call_limit=8)
    form_h1(state)
    current = experiment("H1")

    state.begin_experiment(current)
    assert state.stage is DiagnosisStage.EXECUTING_TOOL
    observation = state.record_observation(successful_tool_result())
    assert state.stage is DiagnosisStage.UPDATING_EVIDENCE
    evidence = state.record_evidence(
        UpdateEvidenceDecision(
            hypothesis_id="H1",
            observation_ref=observation.observation_id,
            direction="contradicting",
            explanation="The explicit value is preserved, contradicting H1.",
        )
    )

    assert state.used_tool_calls == 1
    assert observation.observation_id == "O1"
    assert observation.tool_result_ref == "T1"
    assert observation.artifact_ref == "tool-results/T1.txt"
    assert evidence.evidence_id == "E1"
    assert evidence.observation_ref == "O1"
    assert evidence.provenance == "read_code:tool-results/T1.txt"
    assert state.observations == (observation,)
    assert state.evidence == (evidence,)


def test_observation_rejects_a_tool_result_for_another_experiment() -> None:
    state = DiagnosisStateMachine()
    form_h1(state)
    state.begin_experiment(experiment("H1"))

    with pytest.raises(InvalidDiagnosisTransition, match="current Experiment"):
        state.record_observation(successful_tool_result("X-other"))


def test_observation_and_evidence_reject_out_of_stage_mutation() -> None:
    state = DiagnosisStateMachine()
    form_h1(state)

    with pytest.raises(InvalidDiagnosisTransition, match="executing_tool"):
        state.record_observation(successful_tool_result())
    with pytest.raises(InvalidDiagnosisTransition, match="updating_evidence"):
        state.record_evidence(
            UpdateEvidenceDecision(
                hypothesis_id="H1",
                observation_ref="O1",
                direction="supporting",
                explanation="No registered Observation exists.",
            )
        )

    assert state.observations == ()
    assert state.evidence == ()


def test_tool_budget_stops_before_a_second_execution() -> None:
    state = DiagnosisStateMachine(tool_call_limit=1)
    form_h1(state)
    current = experiment("H1")
    state.begin_experiment(current)
    observation = state.record_observation(successful_tool_result())
    evidence = state.record_evidence(
        UpdateEvidenceDecision(
            hypothesis_id="H1",
            observation_ref=observation.observation_id,
            direction="inconclusive",
            explanation="The code does not discriminate the mechanism.",
        )
    )
    state.apply_hypothesis_assessment(
        HypothesisAssessmentDecision(
            outcome="continue_testing",
            evidence_refs=(evidence.evidence_id,),
            rationale="Another Experiment would be needed.",
        )
    )

    with pytest.raises(InvalidDiagnosisTransition, match="Tool budget exhausted"):
        state.begin_experiment(current.model_copy(update={"experiment_id": "X2"}))
