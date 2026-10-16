"""Minimal explicit lifecycle for bounded initial Hypothesis formation."""

from __future__ import annotations

from .contracts import (
    DiagnosisStage,
    FormHypothesesDecision,
    Hypothesis,
    HypothesisStatus,
)


class InvalidDiagnosisTransition(RuntimeError):
    """Raised when a lifecycle action would violate a state invariant."""


_ALLOWED_TRANSITIONS = {
    DiagnosisStage.PREPARING: frozenset(
        {DiagnosisStage.FORMING_HYPOTHESES, DiagnosisStage.FINALIZING}
    ),
    DiagnosisStage.FORMING_HYPOTHESES: frozenset({DiagnosisStage.FINALIZING}),
    DiagnosisStage.DIAGNOSING: frozenset({DiagnosisStage.FINALIZING}),
    DiagnosisStage.FINALIZING: frozenset(),
}

_ALLOWED_HYPOTHESIS_TRANSITIONS: dict[HypothesisStatus, frozenset[HypothesisStatus]] = {
    "proposed": frozenset({"testing", "rejected", "inconclusive"}),
    "testing": frozenset({"supported", "rejected", "inconclusive"}),
    "supported": frozenset({"testing", "rejected", "inconclusive"}),
    "rejected": frozenset(),
    "inconclusive": frozenset(),
}


class DiagnosisStateMachine:
    """Own lifecycle transitions and the write-once initial Hypothesis set."""

    def __init__(self, stage: DiagnosisStage = DiagnosisStage.PREPARING) -> None:
        self._stage = stage
        self._hypotheses: tuple[Hypothesis, ...] = ()
        self._schema_corrections_used = 0

    @property
    def stage(self) -> DiagnosisStage:
        return self._stage

    @property
    def hypotheses(self) -> tuple[Hypothesis, ...]:
        return self._hypotheses

    @property
    def schema_corrections_used(self) -> int:
        return self._schema_corrections_used

    def transition_to(self, target: DiagnosisStage) -> None:
        if target not in _ALLOWED_TRANSITIONS[self._stage]:
            raise InvalidDiagnosisTransition(
                f"cannot transition from {self._stage.value} to {target.value}"
            )
        self._stage = target

    def authorize_schema_correction(self) -> None:
        if self._stage is not DiagnosisStage.FORMING_HYPOTHESES:
            raise InvalidDiagnosisTransition(
                "Schema correction is only allowed while forming_hypotheses"
            )
        if self._schema_corrections_used >= 1:
            raise InvalidDiagnosisTransition(
                "The Hypothesis formation Schema correction has already been used"
            )
        self._schema_corrections_used += 1

    def form_initial_hypotheses(
        self, decision: FormHypothesesDecision
    ) -> tuple[Hypothesis, ...]:
        if self._stage is not DiagnosisStage.FORMING_HYPOTHESES:
            raise InvalidDiagnosisTransition(
                "initial Hypotheses can only be formed once in forming_hypotheses"
            )
        self._hypotheses = tuple(
            Hypothesis(
                hypothesis_id=f"H{index}",
                root_symbol=proposal.root_symbol,
                location_description=proposal.location_description,
                mechanism=proposal.mechanism,
                falsification_criterion=proposal.falsification_criterion,
            )
            for index, proposal in enumerate(decision.hypotheses, start=1)
        )
        self._stage = DiagnosisStage.DIAGNOSING
        return self._hypotheses

    def transition_hypothesis(
        self, hypothesis_id: str, target: HypothesisStatus
    ) -> Hypothesis:
        if self._stage is not DiagnosisStage.DIAGNOSING:
            raise InvalidDiagnosisTransition(
                "Hypothesis status can only change while diagnosing"
            )
        for index, hypothesis in enumerate(self._hypotheses):
            if hypothesis.hypothesis_id != hypothesis_id:
                continue
            if target not in _ALLOWED_HYPOTHESIS_TRANSITIONS[hypothesis.status]:
                raise InvalidDiagnosisTransition(
                    f"cannot transition Hypothesis {hypothesis_id} from "
                    f"{hypothesis.status} to {target}"
                )
            updated = hypothesis.model_copy(update={"status": target})
            hypotheses = list(self._hypotheses)
            hypotheses[index] = updated
            self._hypotheses = tuple(hypotheses)
            return updated
        raise InvalidDiagnosisTransition(f"unknown Hypothesis {hypothesis_id}")
