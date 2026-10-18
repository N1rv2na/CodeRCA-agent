"""Explicit lifecycle and invariants for bounded Hypothesis History."""

from __future__ import annotations

from .contracts import (
    DecisionValidationError,
    DiagnosisStage,
    Evidence,
    Experiment,
    FormHypothesisDecision,
    Hypothesis,
    HypothesisAssessmentDecision,
    HypothesisProposal,
    HypothesisStatus,
    Observation,
    ReformulateHypothesisDecision,
    ToolResult,
    UpdateEvidenceDecision,
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
        {
            DiagnosisStage.EXECUTING_TOOL,
            DiagnosisStage.FORMING_HYPOTHESIS,
            DiagnosisStage.FINALIZING,
        }
    ),
    DiagnosisStage.EXECUTING_TOOL: frozenset(
        {DiagnosisStage.UPDATING_EVIDENCE, DiagnosisStage.FINALIZING}
    ),
    DiagnosisStage.UPDATING_EVIDENCE: frozenset(
        {
            DiagnosisStage.DIAGNOSING,
            DiagnosisStage.VALIDATING,
            DiagnosisStage.FINALIZING,
        }
    ),
    DiagnosisStage.VALIDATING: frozenset({DiagnosisStage.FINALIZING}),
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

    def __init__(
        self,
        stage: DiagnosisStage = DiagnosisStage.PREPARING,
        *,
        tool_call_limit: int = 8,
    ) -> None:
        if not 1 <= tool_call_limit <= 8:
            raise ValueError("tool_call_limit must be between 1 and 8")
        self._stage = stage
        self._hypothesis_history: tuple[Hypothesis, ...] = ()
        self._schema_corrections_used = 0
        self._tool_call_limit = tool_call_limit
        self._used_tool_calls = 0
        self._current_experiment: Experiment | None = None
        self._experiments: tuple[Experiment, ...] = ()
        self._observations: tuple[Observation, ...] = ()
        self._evidence: tuple[Evidence, ...] = ()

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

    @property
    def used_tool_calls(self) -> int:
        return self._used_tool_calls

    @property
    def remaining_tool_budget(self) -> int:
        return self._tool_call_limit - self._used_tool_calls

    @property
    def tool_budget_exhausted(self) -> bool:
        return self.remaining_tool_budget == 0

    @property
    def current_experiment(self) -> Experiment | None:
        return self._current_experiment

    @property
    def experiments(self) -> tuple[Experiment, ...]:
        return self._experiments

    @property
    def observations(self) -> tuple[Observation, ...]:
        return self._observations

    @property
    def evidence(self) -> tuple[Evidence, ...]:
        return self._evidence

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

    def form_initial_hypothesis(self, decision: FormHypothesisDecision) -> Hypothesis:
        """Append H1 without accepting model-authored Evidence references."""

        self._require_formation_ready()
        if self._hypothesis_history:
            raise InvalidDiagnosisTransition(
                "initial Hypothesis formation requires an empty History"
            )
        return self._append_hypothesis(decision.hypothesis, evidence_basis=())

    def reformulate_hypothesis(
        self,
        decision: ReformulateHypothesisDecision,
    ) -> Hypothesis:
        """Append H2/H3 after resolving every model-cited Evidence ID."""

        self._require_formation_ready()
        if not self._hypothesis_history:
            raise InvalidDiagnosisTransition(
                "Reformulation requires an ended Hypothesis History"
            )

        evidence_by_id = {item.evidence_id: item for item in self._evidence}
        try:
            referenced = [evidence_by_id[item] for item in decision.evidence_refs]
        except KeyError as exc:
            raise InvalidDiagnosisTransition(
                "Reformulation references unknown Evidence"
            ) from exc

        ended_hypothesis_ids = {
            item.hypothesis_id
            for item in self._hypothesis_history
            if item.status in _REFORMULATABLE_STATUSES
        }
        if any(item.hypothesis_id not in ended_hypothesis_ids for item in referenced):
            raise InvalidDiagnosisTransition(
                "Reformulation Evidence must belong to ended Hypothesis History"
            )
        normalized_mechanism = " ".join(
            decision.hypothesis.mechanism.split()
        ).casefold()
        if any(
            " ".join(item.mechanism.split()).casefold() == normalized_mechanism
            for item in self._hypothesis_history
        ):
            raise InvalidDiagnosisTransition(
                "Reformulated Hypothesis mechanism must be materially different"
            )
        return self._append_hypothesis(
            decision.hypothesis, evidence_basis=decision.evidence_refs
        )

    def _require_formation_ready(self) -> None:
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

    def _append_hypothesis(
        self,
        proposal: HypothesisProposal,
        *,
        evidence_basis: tuple[str, ...],
    ) -> Hypothesis:
        hypothesis = Hypothesis(
            hypothesis_id=f"H{len(self._hypothesis_history) + 1}",
            root_symbol=proposal.root_symbol,
            location_description=proposal.location_description,
            mechanism=proposal.mechanism,
            falsification_criterion=proposal.falsification_criterion,
            evidence_basis=evidence_basis,
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

    def begin_experiment(self, experiment: Experiment) -> None:
        """Authorize exactly one Experiment and consume one Tool Budget unit."""

        self.authorize_experiment(experiment)
        if self.tool_budget_exhausted:
            raise InvalidDiagnosisTransition("Tool budget exhausted")
        if self._current_experiment is not None:
            raise InvalidDiagnosisTransition("another Experiment is already active")
        self._current_experiment = experiment
        self._experiments = (*self._experiments, experiment)
        self._used_tool_calls += 1
        self.transition_to(DiagnosisStage.EXECUTING_TOOL)

    def record_observation(self, result: ToolResult) -> Observation:
        """Create an Observation only from the current successful Tool Result."""

        if self._stage is not DiagnosisStage.EXECUTING_TOOL:
            raise InvalidDiagnosisTransition(
                "an Observation can only be recorded while executing_tool"
            )
        experiment = self._current_experiment
        if experiment is None:
            raise InvalidDiagnosisTransition(
                "an Observation requires the current Experiment"
            )
        if result.status != "success":
            raise InvalidDiagnosisTransition(
                "an Observation requires a successful Tool Result"
            )
        if (
            result.experiment_id != experiment.experiment_id
            or result.hypothesis_id != experiment.hypothesis_id
            or result.tool_name != experiment.tool_name
        ):
            raise InvalidDiagnosisTransition(
                "Tool Result must belong to the current Experiment"
            )
        observation = Observation(
            observation_id=f"O{len(self._observations) + 1}",
            experiment_id=experiment.experiment_id,
            hypothesis_id=experiment.hypothesis_id,
            tool_result_ref=result.tool_result_id,
            source=result.tool_name,
            summary=(
                f"{result.tool_name} completed"
                + (" with truncated output" if result.truncated else "")
            ),
            artifact_ref=result.artifact_ref,
            excerpt=result.output,
        )
        self.transition_to(DiagnosisStage.UPDATING_EVIDENCE)
        self._observations = (*self._observations, observation)
        return observation

    def record_evidence(self, decision: UpdateEvidenceDecision) -> Evidence:
        """Create qualitative Evidence linked to a registered Observation."""

        if self._stage is not DiagnosisStage.UPDATING_EVIDENCE:
            raise InvalidDiagnosisTransition(
                "Evidence can only be recorded while updating_evidence"
            )
        active = self.active_hypothesis
        if active is None:
            raise InvalidDiagnosisTransition(
                "Evidence update requires one Active Hypothesis"
            )
        if decision.hypothesis_id != active.hypothesis_id:
            raise InvalidDiagnosisTransition(
                "Evidence must belong to the Active Hypothesis"
            )
        observation = next(
            (
                item
                for item in self._observations
                if item.observation_id == decision.observation_ref
            ),
            None,
        )
        if observation is None:
            raise InvalidDiagnosisTransition(
                "Evidence references an unknown Observation"
            )
        experiment = self._current_experiment
        if experiment is None or observation.experiment_id != experiment.experiment_id:
            raise InvalidDiagnosisTransition(
                "Evidence must reference the current Experiment Observation"
            )
        if observation.hypothesis_id != active.hypothesis_id:
            raise InvalidDiagnosisTransition(
                "Evidence Observation must belong to the Active Hypothesis"
            )
        evidence = Evidence(
            evidence_id=f"E{len(self._evidence) + 1}",
            hypothesis_id=active.hypothesis_id,
            observation_ref=observation.observation_id,
            provenance=f"{observation.source}:{observation.artifact_ref}",
            direction=decision.direction,
            explanation=decision.explanation,
        )
        self._evidence = (*self._evidence, evidence)
        self._current_experiment = None
        return evidence

    def apply_hypothesis_assessment(
        self,
        decision: HypothesisAssessmentDecision,
    ) -> Hypothesis:
        """Map a validated model assessment onto a program-owned transition."""

        if self._stage is not DiagnosisStage.UPDATING_EVIDENCE:
            raise InvalidDiagnosisTransition(
                "Hypothesis assessment is only allowed while updating_evidence"
            )
        try:
            self.validate_hypothesis_assessment(decision)
        except DecisionValidationError as exc:
            raise InvalidDiagnosisTransition(str(exc)) from exc
        active = self.active_hypothesis
        if active is None:  # guarded by validate_hypothesis_assessment
            raise InvalidDiagnosisTransition(
                "Hypothesis assessment requires one Active Hypothesis"
            )

        if decision.outcome == "falsified":
            target: HypothesisStatus = "rejected"
        elif decision.outcome == "sufficiently_supported":
            target = "supported"
        elif decision.outcome == "inconclusive":
            target = "inconclusive"
        else:
            self.transition_to(DiagnosisStage.DIAGNOSING)
            if active.status == "testing":
                return active
            target = "testing"
            return self.transition_hypothesis(active.hypothesis_id, target)
        self.transition_to(DiagnosisStage.DIAGNOSING)
        return self.transition_hypothesis(active.hypothesis_id, target)

    def validate_hypothesis_assessment(
        self, decision: HypothesisAssessmentDecision
    ) -> tuple[Evidence, ...]:
        """Validate model-authored Evidence references without mutating state."""

        if self._stage is not DiagnosisStage.UPDATING_EVIDENCE:
            raise InvalidDiagnosisTransition(
                "Hypothesis assessment is only allowed while updating_evidence"
            )
        active = self.active_hypothesis
        if active is None:
            raise InvalidDiagnosisTransition(
                "Hypothesis assessment requires one Active Hypothesis"
            )
        evidence_by_id = {item.evidence_id: item for item in self._evidence}
        allowed_ids = sorted(
            item.evidence_id
            for item in self._evidence
            if item.hypothesis_id == active.hypothesis_id
        )
        referenced: list[Evidence] = []
        errors: list[dict[str, object]] = []
        for index, evidence_id in enumerate(decision.evidence_refs):
            evidence = evidence_by_id.get(evidence_id)
            if evidence is None:
                errors.append(
                    {
                        "loc": ["evidence_refs", index],
                        "type": "unknown_evidence",
                        "msg": "Evidence ID is not registered.",
                        "input": evidence_id,
                        "allowed_evidence_ids": allowed_ids,
                    }
                )
            elif evidence.hypothesis_id != active.hypothesis_id:
                errors.append(
                    {
                        "loc": ["evidence_refs", index],
                        "type": "evidence_wrong_hypothesis",
                        "msg": "Evidence does not belong to the Active Hypothesis.",
                        "input": evidence_id,
                        "allowed_evidence_ids": allowed_ids,
                    }
                )
            else:
                referenced.append(evidence)
        if errors:
            raise DecisionValidationError(
                "Hypothesis assessment references unknown Evidence", errors
            )

        expected_direction: str | None = None
        message: str | None = None
        if decision.outcome == "falsified":
            expected_direction = "contradicting"
            message = "falsification requires Contradicting Evidence"
        elif decision.outcome == "sufficiently_supported":
            expected_direction = "supporting"
            message = "support requires Supporting Evidence"
        if expected_direction is not None and not any(
            item.direction == expected_direction for item in referenced
        ):
            raise DecisionValidationError(
                message or "Evidence direction is incompatible with assessment",
                [
                    {
                        "loc": ["evidence_refs"],
                        "type": "incompatible_evidence_direction",
                        "msg": message
                        or "Evidence direction is incompatible with assessment.",
                        "expected_direction": expected_direction,
                        "referenced_directions": [
                            item.direction for item in referenced
                        ],
                    }
                ],
            )
        return tuple(referenced)
