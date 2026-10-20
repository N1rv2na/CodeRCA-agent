"""Decision-specific reconstructed Working Context projections."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import Evidence, Experiment, Hypothesis, Observation, TaskManifest
from .diagnosis_state import DiagnosisStateMachine, InvalidDiagnosisTransition


def _evidence_direction_contract() -> dict[str, str]:
    return {
        "reference": "active_hypothesis.mechanism",
        "supporting": "Positive observed facts support the stated mechanism.",
        "contradicting": "Observed facts oppose the stated mechanism.",
        "inconclusive": "Insufficient, mixed, or ambiguous relation to the mechanism.",
        "warning": "Not relative to falsification_criterion or expected_observation; "
        "failure to falsify alone does not establish support.",
    }


@dataclass(frozen=True)
class DiagnosisTaskContext:
    manifest: TaskManifest
    ci_failure_excerpt: str
    ci_failure_artifact: str
    ci_failure_truncated: bool = False


def resolve_task_context(
    manifest: TaskManifest,
    task_directory: Path,
    *,
    ci_excerpt_limit: int = 2_000,
) -> DiagnosisTaskContext:
    """Resolve a Manifest artifact without permitting task-directory escape."""

    root = Path(task_directory).resolve()
    artifact = (root / manifest.ci_log).resolve()
    try:
        artifact.relative_to(root)
    except ValueError as exc:
        raise ValueError("CI artifact must remain inside the task directory") from exc
    if not artifact.is_file():
        raise FileNotFoundError(f"CI artifact does not exist: {manifest.ci_log}")
    content = artifact.read_text(encoding="utf-8")
    excerpt = content[:ci_excerpt_limit]
    return DiagnosisTaskContext(
        manifest=manifest,
        ci_failure_excerpt=excerpt,
        ci_failure_artifact=manifest.ci_log,
        ci_failure_truncated=len(content) > len(excerpt),
    )


class ContextBuilder:
    def __init__(
        self,
        *,
        task_excerpt_limit: int = 2_000,
        observation_excerpt_limit: int = 2_000,
    ) -> None:
        self.task_excerpt_limit = task_excerpt_limit
        self.observation_excerpt_limit = observation_excerpt_limit

    def build_form_hypothesis(
        self,
        task: DiagnosisTaskContext,
        state: DiagnosisStateMachine,
        *,
        observations: list[Observation] | None = None,
        evidence: list[Evidence] | None = None,
        available_tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        evidence = evidence or []
        observations = observations or []
        history = state.hypothesis_history
        context: dict[str, Any] = {
            "decision_type": (
                "form_hypothesis" if not history else "reformulate_hypothesis"
            ),
            "task_context": self._task_context(task),
            "diagnosis_state": self._diagnosis_state(
                task, state, used_tool_calls=state.used_tool_calls
            ),
        }
        if history:
            ended_ids = {
                item.hypothesis_id
                for item in history
                if item.status in {"rejected", "inconclusive"}
            }
            context["reformulation_knowledge"] = {
                "evidence": self._dump_evidence(evidence, ended_ids),
                "observations": self._dump_observations(observations, ended_ids),
            }
            context["available_tools"] = available_tools or []
        return context

    def build_select_experiment(
        self,
        task: DiagnosisTaskContext,
        state: DiagnosisStateMachine,
        *,
        available_tools: list[dict[str, Any]],
        experiments: list[Experiment],
        observations: list[Observation],
        evidence: list[Evidence],
        used_tool_calls: int,
    ) -> dict[str, Any]:
        active = self._require_active(state)
        relevant_ids = {active.hypothesis_id}
        return {
            "decision_type": "select_experiment",
            "evidence_basis_knowledge": self._evidence_basis_knowledge(
                active, evidence, observations
            ),
            "available_tools": available_tools,
            "task_context": self._task_context(task),
            "diagnosis_state": self._diagnosis_state(
                task, state, used_tool_calls=used_tool_calls
            ),
            "active_hypothesis": active.model_dump(mode="json"),
            "relevant_previous_experiments": [
                item.model_dump(mode="json")
                for item in experiments
                if item.hypothesis_id in relevant_ids
            ],
            "relevant_observations": self._dump_observations(
                observations, relevant_ids
            ),
            "relevant_evidence": self._dump_evidence(evidence, relevant_ids),
        }

    def build_update_evidence(
        self,
        task: DiagnosisTaskContext,
        state: DiagnosisStateMachine,
        *,
        experiment: Experiment,
        latest_observation: Observation,
        evidence: list[Evidence],
    ) -> dict[str, Any]:
        active = self._require_active(state)
        if experiment.hypothesis_id != active.hypothesis_id:
            raise InvalidDiagnosisTransition(
                "the current Experiment must belong to the Active Hypothesis"
            )
        if latest_observation.experiment_id != experiment.experiment_id:
            raise InvalidDiagnosisTransition(
                "the latest Observation must belong to the current Experiment"
            )
        if latest_observation.hypothesis_id != active.hypothesis_id:
            raise InvalidDiagnosisTransition(
                "the latest Observation must belong to the Active Hypothesis"
            )
        excerpt = latest_observation.excerpt[: self.observation_excerpt_limit]
        observation_view = latest_observation.model_dump(mode="json")
        observation_view["excerpt"] = excerpt
        observation_view["truncated"] = len(latest_observation.excerpt) > len(excerpt)
        relevant_ids = {active.hypothesis_id}
        return {
            "decision_type": "update_evidence",
            "evidence_direction_contract": _evidence_direction_contract(),
            "active_hypothesis": active.model_dump(mode="json"),
            "current_experiment": experiment.model_dump(mode="json"),
            "latest_observation": observation_view,
            "evidence_basis_knowledge": self._evidence_basis_knowledge(
                active, evidence, list(state.observations)
            ),
            "existing_relevant_evidence": self._dump_evidence(evidence, relevant_ids),
        }

    def build_assess_hypothesis(
        self,
        task: DiagnosisTaskContext,
        state: DiagnosisStateMachine,
        *,
        available_tools: list[dict[str, Any]],
        observations: list[Observation],
        evidence: list[Evidence],
        used_tool_calls: int,
    ) -> dict[str, Any]:
        active = self._require_active(state)
        relevant_ids = {active.hypothesis_id}
        return {
            "decision_type": "assess_hypothesis",
            "evidence_direction_contract": _evidence_direction_contract(),
            "assessment_requirements": {
                "sufficiently_supported": "supporting",
                "falsified": "contradicting",
                "rule": "At least one cited Evidence must have the required "
                "registered direction; necessary but not sufficient. "
                "Never relabel existing Evidence. If labels and facts "
                "conflict, use continue_testing for a targeted new "
                "Experiment, or inconclusive if no useful test remains.",
            },
            "task_context": self._task_context(task),
            "available_tools": available_tools,
            "diagnosis_state": self._diagnosis_state(
                task, state, used_tool_calls=used_tool_calls
            ),
            "active_hypothesis": active.model_dump(mode="json"),
            "evidence_basis_knowledge": self._evidence_basis_knowledge(
                active, evidence, observations
            ),
            "relevant_evidence": self._dump_evidence(evidence, relevant_ids),
            "relevant_observations": self._dump_observations_with_excerpt(
                observations,
                relevant_ids,
                excerpt_limit=self.observation_excerpt_limit,
            ),
        }

    def build_validation(
        self,
        task: DiagnosisTaskContext,
        state: DiagnosisStateMachine,
        *,
        observations: list[Observation],
        evidence: list[Evidence],
    ) -> dict[str, Any]:
        supported = state.supported_hypothesis
        if supported is None:
            raise InvalidDiagnosisTransition(
                "Validation requires one supported Hypothesis"
            )
        relevant_ids = {supported.hypothesis_id}
        return {
            "decision_type": "validate_hypothesis",
            "task_context": self._task_context(task),
            "supported_hypothesis": supported.model_dump(mode="json"),
            "evidence_basis_knowledge": self._evidence_basis_knowledge(
                supported, evidence, observations
            ),
            "relevant_evidence": self._dump_evidence(evidence, relevant_ids),
            "relevant_observations": self._dump_observations_with_excerpt(
                observations,
                relevant_ids,
                excerpt_limit=self.observation_excerpt_limit,
            ),
        }

    def _task_context(self, task: DiagnosisTaskContext) -> dict[str, Any]:
        manifest = task.manifest
        excerpt = task.ci_failure_excerpt[: self.task_excerpt_limit]
        return {
            "task_id": manifest.task_id,
            "repository_id": manifest.repository_id,
            "base_snapshot": manifest.base_snapshot,
            "faulty_commit": manifest.faulty_commit,
            "test_command_id": manifest.test_command_id,
            "execution_boundary": {
                "docker_image": manifest.docker_image,
                "read_paths": manifest.read_paths,
                "write_paths": manifest.write_paths,
            },
            "ci_failure": {
                "excerpt": excerpt,
                "artifact_ref": task.ci_failure_artifact,
                "truncated": (
                    task.ci_failure_truncated
                    or len(task.ci_failure_excerpt) > len(excerpt)
                ),
            },
        }

    @staticmethod
    def _diagnosis_state(
        task: DiagnosisTaskContext,
        state: DiagnosisStateMachine,
        *,
        used_tool_calls: int,
    ) -> dict[str, Any]:
        return {
            "stage": state.stage.value,
            "hypothesis_history": [
                item.model_dump(mode="json") for item in state.hypothesis_history
            ],
            "active_hypothesis_id": (
                state.active_hypothesis.hypothesis_id
                if state.active_hypothesis is not None
                else None
            ),
            "remaining_hypothesis_budget": state.remaining_hypothesis_budget,
            "remaining_tool_budget": max(
                task.manifest.tool_call_limit - used_tool_calls, 0
            ),
            "used_experiment_budget": (
                state.used_experiments_for_active_hypothesis
            ),
            "remaining_experiment_budget": state.remaining_experiment_budget,
        }

    @staticmethod
    def _require_active(state: DiagnosisStateMachine) -> Hypothesis:
        active = state.active_hypothesis
        if active is None:
            raise InvalidDiagnosisTransition(
                "this decision requires one Active Hypothesis"
            )
        return active

    @staticmethod
    def _dump_evidence(
        evidence: list[Evidence], hypothesis_ids: set[str]
    ) -> list[dict[str, Any]]:
        return [
            item.model_dump(mode="json")
            for item in evidence
            if item.hypothesis_id in hypothesis_ids
        ]

    def _evidence_basis_knowledge(
        self,
        hypothesis: Hypothesis,
        evidence: list[Evidence],
        observations: list[Observation],
    ) -> dict[str, list[dict[str, Any]]]:
        evidence_by_id = {item.evidence_id: item for item in evidence}
        selected_evidence = [
            evidence_by_id[evidence_id]
            for evidence_id in hypothesis.evidence_basis
            if evidence_id in evidence_by_id
        ]
        observation_by_id = {
            item.observation_id: item for item in observations
        }
        selected_observations = [
            observation_by_id[item.observation_ref]
            for item in selected_evidence
            if item.observation_ref in observation_by_id
        ]
        return {
            "evidence": [
                item.model_dump(mode="json") for item in selected_evidence
            ],
            "observations": self._dump_observations_with_excerpt(
                selected_observations,
                {item.hypothesis_id for item in selected_evidence},
                excerpt_limit=self.observation_excerpt_limit,
            ),
        }

    @staticmethod
    def _dump_observations(
        observations: list[Observation], hypothesis_ids: set[str]
    ) -> list[dict[str, Any]]:
        views: list[dict[str, Any]] = []
        for item in observations:
            if item.hypothesis_id not in hypothesis_ids:
                continue
            view = item.model_dump(mode="json", exclude={"excerpt"})
            views.append(view)
        return views

    @staticmethod
    def _dump_observations_with_excerpt(
        observations: list[Observation],
        hypothesis_ids: set[str],
        *,
        excerpt_limit: int,
    ) -> list[dict[str, Any]]:
        views: list[dict[str, Any]] = []
        for item in observations:
            if item.hypothesis_id not in hypothesis_ids:
                continue
            excerpt = item.excerpt[:excerpt_limit]
            view = item.model_dump(mode="json")
            view["excerpt"] = excerpt
            view["truncated"] = len(item.excerpt) > len(excerpt)
            views.append(view)
        return views
