"""Author-only Task 2 acceptance; not an Agent tool or a general evaluator.

Checks structural Outcome/Trajectory evidence. Causal correctness and meaningful
use of search still require the documented human review, not keyword scoring.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .benchmark import load_task_2_manifest
from .contracts import (
    DiagnosisEvent,
    DiagnosisReport,
    HypothesisAssessmentDecision,
)
from .tool_runtime import SearchCodeResult


def check_task_2_run(directory: Path) -> dict[str, Any]:
    """Fail closed on missing artifacts; never load truth into diagnosis context."""
    directory = directory.resolve()

    def artifact(ref: str) -> Path:
        path = (directory / ref).resolve()
        if Path(ref).is_absolute() or not path.is_relative_to(directory):
            raise ValueError("artifact escapes Run Directory")
        if not path.is_file():
            raise ValueError(f"missing artifact: {ref}")
        return path

    try:
        report = DiagnosisReport.model_validate_json(
            artifact("report.json").read_text()
        )
        events = [
            DiagnosisEvent.model_validate_json(line)
            for line in artifact("events.jsonl").read_text().splitlines()
            if line.strip()
        ]
        manifest = load_task_2_manifest()
        if json.loads(artifact("manifest.json").read_text()) != manifest.model_dump(
            mode="json"
        ):
            raise ValueError("Run Manifest is not frozen Task 2")
        if report.task_id != manifest.task_id or any(
            e.run_id != report.run_id or e.task_id != report.task_id for e in events
        ):
            raise ValueError("inconsistent Run identity")
        final = report.final_hypothesis
        outcome = bool(
            report.status == "completed"
            and final
            and final.status == "supported"
            and final.root_symbol in ("keyfmt", "waffle.utils.keyfmt")
            and report.patch
            and report.patch.hypothesis_id == final.hypothesis_id
            and report.validation
            and report.validation.status == "passed"
            and report.validation.hypothesis_id == final.hypothesis_id
            and report.root_cause_analysis
        )
        if report.validation:
            artifact(report.validation.artifact_ref)
            artifact(report.validation.patch_artifact_ref)
            for check in (
                report.validation.static_check,
                report.validation.registered_test,
            ):
                if check:
                    artifact(check.artifact_ref)
        used: set[str] = set()
        for event in events:
            if (
                event.event_type != "hypothesis_assessed"
                or not event.model_response_artifact
            ):
                continue
            if not final or not any(
                h.hypothesis_id == final.hypothesis_id and h.status == "supported"
                for h in event.hypothesis_history
            ):
                continue
            raw = json.loads(artifact(event.model_response_artifact).read_text())
            # Existing Fake and HTTP providers persist different envelope shapes.
            if "choices" in raw:
                raw = json.loads(raw["choices"][0]["message"]["content"])
            assessment = HypothesisAssessmentDecision.model_validate(raw)
            used.update(assessment.evidence_refs)
        sources: set[str] = set()
        # Reformulation can carry earlier rejected-H knowledge into the final H.
        relevant_hypotheses = {final.hypothesis_id} if final else set()
        if final:
            used.update(final.evidence_basis)
        for hypothesis in reversed(report.hypothesis_history):
            if hypothesis.hypothesis_id in relevant_hypotheses:
                used.update(hypothesis.evidence_basis)
            relevant_hypotheses.update(
                e.hypothesis_id for e in report.evidence if e.evidence_id in used
            )
        for evidence in report.evidence:
            if not final or evidence.evidence_id not in used:
                continue
            observation = next(
                (
                    o
                    for o in report.observations
                    if o.observation_id == evidence.observation_ref
                ),
                None,
            )
            if (
                observation is None
                or observation.hypothesis_id != evidence.hypothesis_id
            ):
                continue
            artifact(observation.artifact_ref)
            for event in events:
                result, experiment = event.tool_result, event.experiment
                if not result or not experiment:
                    continue
                if (
                    result.tool_result_id == observation.tool_result_ref
                    and result.status == "success"
                    and result.artifact_ref == observation.artifact_ref
                    and result.hypothesis_id
                    == experiment.hypothesis_id
                    == evidence.hypothesis_id
                    and result.experiment_id
                    == experiment.experiment_id
                    == observation.experiment_id
                    and result.tool_name == experiment.tool_name == observation.source
                    and evidence.provenance
                    == f"{observation.source}:{observation.artifact_ref}"
                ):
                    if observation.source == "search_code":
                        search = SearchCodeResult.model_validate_json(
                            artifact(observation.artifact_ref).read_text()
                        )
                        if search.status != "matched" or not search.matches:
                            continue
                    sources.add(observation.source)
        trajectory = "search_code" in sources and bool(
            sources & {"read_code", "inspect_diff"}
        )
        return {
            "outcome_pass": outcome,
            "trajectory_pass": trajectory,
            "trajectory_review": (
                "linked_evidence" if trajectory else "not_proven_by_structured_refs"
            ),
            "structural_pass": outcome and trajectory,
            "human_review_required": True,
        }
    except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
        return {
            "structural_pass": False,
            "human_review_required": True,
            "error": str(exc),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_directory", type=Path)
    args = parser.parse_args()
    result = check_task_2_run(args.run_directory)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["structural_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
