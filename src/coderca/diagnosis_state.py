"""Explicit lifecycle and invariants for bounded Hypothesis History."""

from __future__ import annotations

from .contracts import (
    DiagnosisStage,
    Evidence,
    Experiment,
    FormHypothesisDecision,
    Hypothesis,
    HypothesisAssessmentDecision,
    HypothesisStatus,
)

_MAX_HYPOTHESES = 3
_ACTIVE_STATUSES = frozenset({"proposed", "testing"})
_REFORMULATABLE_STATUSES = frozenset({"rejected", "inconclusive"})


class InvalidDiagnosisTransition(RuntimeError):
    """Raised when a lifecycle action would violate a state invariant."""


_ALLOWED_TRANSITIONS = {
    DiagnosisStage.PREPARING: frozenset(
        {DiagnosisStage.FORMING_HYPOTHESIS, DiagnosisStage.FINALIZING}
    ),
    DiagnosisStage.FORMING_HYPOTHESIS: frozenset({DiagnosisStage.FINALIZING}),
    DiagnosisStage.DIAGNOSING: frozenset(
        {DiagnosisStage.FORMING_HYPOTHESIS, DiagnosisStage.FINALIZING}
    ),
    DiagnosisStage.FINALIZING: frozenset(),
}

_ALLOWED_HYPOTHESIS_TRANSITIONS: dict[HypothesisStatus, frozenset[HypothesisStatus]] = {
    "proposed": frozenset({"testing", "supported", "rejected", "inconclusive"}),
    "testing": frozenset({"supported", "rejected", "inconclusive"}),
    "supported": frozenset(),
    "rejected": frozenset(),
    "inconclusive": frozenset(),
}


class DiagnosisStateMachine:
    """Own lifecycle, append-only Hypothesis History, IDs, and budgets."""

    def __init__(self, stage: DiagnosisStage = DiagnosisStage.PREPARING) -> None:
        self._stage = stage
        self._hypothesis_history: tuple[Hypothesis, ...] = ()
        self._schema_corrections_used = 0

    @property
    def stage(self) -> DiagnosisStage:
        return self._stage

    @property
    def hypothesis_history(self) -> tuple[Hypothesis, ...]:
        return self._hypothesis_history

    @property
    def active_hypothesis(self) -> Hypothesis | None:
        active = [
            item for item in self._hypothesis_history if item.status in _ACTIVE_STATUSES
        ]
        if len(active) > 1:  # defensive guard against corrupted state
            raise InvalidDiagnosisTransition("more than one Active Hypothesis exists")
        return active[0] if active else None

    @property
    def supported_hypothesis(self) -> Hypothesis | None:
        supported = [
            item for item in self._hypothesis_history if item.status == "supported"
        ]
        return supported[0] if supported else None

    @property
    def remaining_hypothesis_budget(self) -> int:
        return _MAX_HYPOTHESES - len(self._hypothesis_history)

    @property
    def hypothesis_budget_exhausted(self) -> bool:
        return self.remaining_hypothesis_budget == 0

    @property
    def schema_corrections_used(self) -> int:
        return self._schema_corrections_used

    def transition_to(self, target: DiagnosisStage) -> None:
        if target not in _ALLOWED_TRANSITIONS[self._stage]:
            raise InvalidDiagnosisTransition(
                f"cannot transition from {self._stage.value} to {target.value}"
            )
        self._stage = target

    def begin_hypothesis_formation(self) -> None:
        if self._stage is DiagnosisStage.FINALIZING:
            raise InvalidDiagnosisTransition(
                "cannot form a Hypothesis after Finalizing"
            )
        active = self.active_hypothesis
        if active is not None:
            raise InvalidDiagnosisTransition(
                f"active Hypothesis {active.hypothesis_id} must end before "
                "reformulation"
            )
        if self.supported_hypothesis is not None:
            raise InvalidDiagnosisTransition(
                "a supported Hypothesis proceeds to Validation, not reformulation"
            )
        if self.hypothesis_budget_exhausted:
            raise InvalidDiagnosisTransition(
                "Hypothesis budget exhausted; H4 is forbidden"
            )
        if self._hypothesis_history:
            latest = self._hypothesis_history[-1]
            if latest.status not in _REFORMULATABLE_STATUSES:
                raise InvalidDiagnosisTransition(
                    "the current Hypothesis must end before reformulation"
                )
        self.transition_to(DiagnosisStage.FORMING_HYPOTHESIS)
        self._schema_corrections_used = 0

    def authorize_schema_correction(self) -> None:
        if self._stage is not DiagnosisStage.FORMING_HYPOTHESIS:
            raise InvalidDiagnosisTransition(
                "Schema correction is only allowed while forming_hypothesis"
            )
        if self._schema_corrections_used >= 1:
            raise InvalidDiagnosisTransition(
                "The Hypothesis formation Schema correction has already been used"
            )
        self._schema_corrections_used += 1

    def form_hypothesis(self, decision: FormHypothesisDecision) -> Hypothesis:
        if self._stage is not DiagnosisStage.FORMING_HYPOTHESIS:
            raise InvalidDiagnosisTransition(
                "a Hypothesis can only be formed in forming_hypothesis"
            )
        if self.active_hypothesis is not None:
            raise InvalidDiagnosisTransition("only one Active Hypothesis is allowed")
        if self.hypothesis_budget_exhausted:
            raise InvalidDiagnosisTransition(
                "Hypothesis budget exhausted; H4 is forbidden"
            )
        if self._hypothesis_history and not decision.hypothesis.evidence_basis:
            raise InvalidDiagnosisTransition(
                "a reformulated Hypothesis requires an evidence basis"
            )

        proposal = decision.hypothesis
        hypothesis = Hypothesis(
            hypothesis_id=f"H{len(self._hypothesis_history) + 1}",
            root_symbol=proposal.root_symbol,
            location_description=proposal.location_description,
            mechanism=proposal.mechanism,
            falsification_criterion=proposal.falsification_criterion,
            evidence_basis=proposal.evidence_basis,
        )
        self._hypothesis_history = (*self._hypothesis_history, hypothesis)
        self._stage = DiagnosisStage.DIAGNOSING
        return hypothesis

    def transition_hypothesis(
        self, hypothesis_id: str, target: HypothesisStatus
    ) -> Hypothesis:
        if self._stage is not DiagnosisStage.DIAGNOSING:
            raise InvalidDiagnosisTransition(
                "Hypothesis status can only change while diagnosing"
            )
        for index, hypothesis in enumerate(self._hypothesis_history):
            if hypothesis.hypothesis_id != hypothesis_id:
                continue
            if target not in _ALLOWED_HYPOTHESIS_TRANSITIONS[hypothesis.status]:
                raise InvalidDiagnosisTransition(
                    f"cannot transition Hypothesis {hypothesis_id} from "
                    f"{hypothesis.status} to {target}"
                )
            active = self.active_hypothesis
            if active is not None and active.hypothesis_id != hypothesis_id:
                raise InvalidDiagnosisTransition(
                    f"Hypothesis {active.hypothesis_id} is already active"
                )
            updated = hypothesis.model_copy(update={"status": target})
            history = list(self._hypothesis_history)
            history[index] = updated
            self._hypothesis_history = tuple(history)
            return updated
        raise InvalidDiagnosisTransition(f"unknown Hypothesis {hypothesis_id}")

    def authorize_experiment(self, experiment: Experiment) -> None:
        """Validate binding before a Tool Runtime may execute the Experiment."""

        if self._stage is not DiagnosisStage.DIAGNOSING:
            raise InvalidDiagnosisTransition(
                "an Experiment can only be authorized while diagnosing"
            )
        active = self.active_hypothesis
        if active is None:
            raise InvalidDiagnosisTransition(
                "an Experiment requires one Active Hypothesis"
            )
        if experiment.hypothesis_id != active.hypothesis_id:
            raise InvalidDiagnosisTransition(
                f"Experiment must bind the Active Hypothesis {active.hypothesis_id}"
            )

    def apply_hypothesis_assessment(
        self,
        decision: HypothesisAssessmentDecision,
        *,
        evidence: list[Evidence],
    ) -> Hypothesis:
        """Map a validated model assessment onto a program-owned transition."""

        active = self.active_hypothesis
        if active is None:
            raise InvalidDiagnosisTransition(
                "Hypothesis assessment requires one Active Hypothesis"
            )
        evidence_by_id = {item.evidence_id: item for item in evidence}
        try:
            referenced = [evidence_by_id[item] for item in decision.evidence_refs]
        except KeyError as exc:
            raise InvalidDiagnosisTransition(
                "Hypothesis assessment references unknown Evidence"
            ) from exc
        if any(item.hypothesis_id != active.hypothesis_id for item in referenced):
            raise InvalidDiagnosisTransition(
                "Hypothesis assessment Evidence must belong to the Active Hypothesis"
            )

        if decision.outcome == "falsified":
            if not any(item.direction == "contradicting" for item in referenced):
                raise InvalidDiagnosisTransition(
                    "falsification requires Contradicting Evidence"
                )
            target: HypothesisStatus = "rejected"
        elif decision.outcome == "sufficiently_supported":
            if not any(item.direction == "supporting" for item in referenced):
                raise InvalidDiagnosisTransition(
                    "support requires Supporting Evidence"
                )
            target = "supported"
        elif decision.outcome == "inconclusive":
            target = "inconclusive"
        else:
            if active.status == "testing":
                return active
            target = "testing"
        return self.transition_hypothesis(active.hypothesis_id, target)
