"""Author-only Task 3 self-correction checks; causal review remains manual."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence, TypeVar

from pydantic import BaseModel

from .benchmark import load_task_3_manifest
from .contracts import (
    DecisionValidationError,
    DiagnosisEvent,
    Hypothesis,
    HypothesisAssessmentDecision,
    PublicValidationResult,
    ReformulateHypothesisDecision,
)
from .localization import (
    artifact_path,
    audit_evidence,
    normalize_legacy_report,
    read_persisted_report,
    validate_location_sources,
)

_ROOT_PATH = "waffle/decorators.py"
_ROOT_SYMBOLS = {
    "waffle_flag",
    "waffle.decorators.waffle_flag",
    "waffle_flag._wrapped_view",
    "waffle.decorators.waffle_flag._wrapped_view",
}
_DEFECT_LINE = 20
_ACTIVE_STATUSES = {"proposed", "testing"}
_TERMINAL_STATUSES = {"supported", "rejected", "inconclusive"}
_Model = TypeVar("_Model", bound=BaseModel)


def _model_artifact(
    directory: Path, event: DiagnosisEvent, model: type[_Model]
) -> _Model:
    if not event.model_response_artifact:
        raise ValueError(f"{event.event_type} missing model response artifact")
    raw = json.loads(
        artifact_path(directory, event.model_response_artifact).read_text()
    )
    if isinstance(raw, dict) and "choices" in raw:
        raw = json.loads(raw["choices"][0]["message"]["content"])
    return model.model_validate(raw)


def _audit_history(events: list[DiagnosisEvent], final: list[Hypothesis]) -> None:
    final_ids = [item.hypothesis_id for item in final]
    if final_ids != ["H1", "H2"]:
        raise ValueError("Task 3 requires exactly append-only H1 then H2")
    previous_ids: list[str] = []
    terminal: dict[str, str] = {}
    immutable = {
        item.hypothesis_id: item.model_dump(exclude={"status"}) for item in final
    }
    for event in events:
        history = event.hypothesis_history
        ids = [item.hypothesis_id for item in history]
        if ids != final_ids[: len(ids)] or len(ids) < len(previous_ids):
            raise ValueError("Hypothesis History is not an append-only H1/H2 prefix")
        previous_ids = ids
        if sum(item.status in _ACTIVE_STATUSES for item in history) > 1:
            raise ValueError("more than one Active Hypothesis appears in an event")
        for item in history:
            if item.model_dump(exclude={"status"}) != immutable[item.hypothesis_id]:
                raise ValueError("Hypothesis identity or content changed in History")
            prior_terminal = terminal.get(item.hypothesis_id)
            if prior_terminal is not None and item.status != prior_terminal:
                raise ValueError("terminal Hypothesis was changed or revived")
            if item.status in _TERMINAL_STATUSES:
                terminal[item.hypothesis_id] = item.status


def check_task_3_run(directory: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "audit_error": None,
        "causal_review": "required",
        "h1_falsified": False,
        "h2_reformulated": False,
        "human_review_required": True,
        "outcome_pass": False,
        "repair_validation": "not_run",
        "trajectory_pass": False,
    }
    try:
        report = read_persisted_report(
            json.loads(artifact_path(directory, "report.json").read_text())
        )
        events = [
            DiagnosisEvent.model_validate(normalize_legacy_report(json.loads(line)))
            for line in (
                artifact_path(directory, "events.jsonl").read_text().splitlines()
            )
            if line.strip()
        ]
        manifest = load_task_3_manifest()
        if json.loads(artifact_path(directory, "manifest.json").read_text()) != (
            manifest.model_dump(mode="json")
        ):
            raise ValueError("Run Manifest is not frozen Task 3")
        if report.task_id != manifest.task_id or any(
            event.run_id != report.run_id or event.task_id != report.task_id
            for event in events
        ):
            raise ValueError("inconsistent Run identity")
        if [event.sequence for event in events] != list(range(1, len(events) + 1)):
            raise ValueError("invalid event sequence")
        if len({entry.evidence_id for entry in report.evidence}) != len(
            report.evidence
        ):
            raise ValueError("duplicate Evidence ID")

        history = report.hypothesis_history
        _audit_history(events, history)
        h1, h2 = history
        if h1.evidence_basis:
            raise ValueError("H1 Evidence Basis must be empty")
        if h1.status != "rejected" or h2.status != "supported":
            raise ValueError("Task 3 requires rejected H1 and supported H2")
        if h1.root_symbol in _ROOT_SYMBOLS or (
            h1.location_description and _ROOT_PATH in h1.location_description
        ):
            raise ValueError("H1 already names the canonical Task 3 Root Cause")
        if " ".join(h1.mechanism.split()).casefold() == " ".join(
            h2.mechanism.split()
        ).casefold():
            raise ValueError("H2 does not contain a materially different mechanism")

        evidence_by_id = {entry.evidence_id: entry for entry in report.evidence}
        if not h2.evidence_basis or len(set(h2.evidence_basis)) != len(
            h2.evidence_basis
        ):
            raise ValueError("H2 requires a non-empty unique Evidence Basis")
        try:
            basis = [evidence_by_id[ref] for ref in h2.evidence_basis]
        except KeyError as exc:
            raise ValueError("H2 Evidence Basis references unknown Evidence") from exc
        if any(
            entry.hypothesis_id != "H1" or entry.direction != "contradicting"
            for entry in basis
        ):
            raise ValueError("H2 Basis must contain only H1 Contradicting Evidence")

        h1_test_evidence = []
        for entry in basis:
            observation, tool_event, content = audit_evidence(
                entry, report.observations, events, directory
            )
            experiment = tool_event.experiment
            tool_result = tool_event.tool_result
            if (
                observation.source == "run_tests"
                and experiment is not None
                and tool_result is not None
                and experiment.hypothesis_id == "H1"
                and experiment.tool_name == "run_tests"
                and experiment.arguments
                == {"test_command_id": manifest.test_command_id}
                and tool_result.command_id == manifest.test_command_id
                and "CRCA_TASK_3_EXPECTED_ASSERTION_MISMATCH" in content
                and "direct_flag_state=False" in content
                and "inverse_guard_denied=True" in content
            ):
                h1_test_evidence.append(entry)
        if not h1_test_evidence:
            raise ValueError(
                "H1 lacks artifact-backed Contradicting run_tests Evidence"
            )

        h1_assessments = [
            event
            for event in events
            if event.event_type == "hypothesis_assessed"
            and event.hypothesis_history
            and event.hypothesis_history[-1].hypothesis_id == "H1"
        ]
        if len(h1_assessments) != 1:
            raise ValueError("Task 3 requires exactly one terminal H1 assessment")
        if [
            (item.hypothesis_id, item.status)
            for item in h1_assessments[0].hypothesis_history
        ] != [("H1", "rejected")]:
            raise ValueError("H1 must be persisted as rejected when assessed")
        h1_assessment = _model_artifact(
            directory, h1_assessments[0], HypothesisAssessmentDecision
        )
        if h1_assessment.outcome != "falsified" or not set(
            h1_assessment.evidence_refs
        ).issubset({entry.evidence_id for entry in h1_test_evidence}):
            raise ValueError("H1 was not falsified by its run_tests Evidence")

        reformulations = [
            event for event in events if event.event_type == "hypothesis_reformulated"
        ]
        if len(reformulations) != 1:
            raise ValueError("Task 3 requires exactly one H2 Reformulation")
        reformulation = reformulations[0]
        if reformulation.sequence <= h1_assessments[0].sequence:
            raise ValueError("H2 appeared before H1 rejection")
        if [
            (item.hypothesis_id, item.status)
            for item in reformulation.hypothesis_history
        ] != [("H1", "rejected"), ("H2", "proposed")]:
            raise ValueError(
                "Reformulation event must persist rejected H1 and Active H2"
            )
        decision = _model_artifact(
            directory, reformulation, ReformulateHypothesisDecision
        )
        if decision.evidence_refs != h2.evidence_basis:
            raise ValueError("persisted H2 Basis differs from Reformulation decision")
        result["h1_falsified"] = True
        result["h2_reformulated"] = True

        final = report.final_hypothesis
        if final != h2:
            raise ValueError("final Hypothesis is not the supported H2")
        h2_assessments = [
            event
            for event in events
            if event.event_type == "hypothesis_assessed"
            and [item.hypothesis_id for item in event.hypothesis_history]
            == ["H1", "H2"]
        ]
        if len(h2_assessments) != 1 or [
            (item.hypothesis_id, item.status)
            for item in h2_assessments[0].hypothesis_history
        ] != [("H1", "rejected"), ("H2", "supported")]:
            raise ValueError("Task 3 requires one persisted supported H2 assessment")
        if reformulation.sequence >= h2_assessments[0].sequence:
            raise ValueError("H2 must be reformulated before it is supported")
        analysis = report.root_cause_analysis
        if analysis is None or analysis.location is None:
            raise ValueError("Task 3 final Root Cause location is missing")
        validate_location_sources(
            analysis.location,
            h2.hypothesis_id,
            manifest,
            report.evidence,
            report.observations,
            events,
            directory,
            evidence_basis=h2.evidence_basis,
        )
        location = analysis.location
        if not (
            location.path == _ROOT_PATH
            and location.symbol in _ROOT_SYMBOLS
            and location.start_line <= _DEFECT_LINE <= location.end_line
        ):
            raise ValueError("Task 3 final Root Cause location does not match truth")

        validation = report.validation
        patch = report.patch
        if validation is None or patch is None:
            raise ValueError("Task 3 requires a Candidate Patch and Validation")
        if patch.hypothesis_id != "H2" or validation.hypothesis_id != "H2":
            raise ValueError("only supported H2 may patch and validate")
        patch_events = [
            event for event in events if event.event_type == "patch_generated"
        ]
        validation_events = [
            event for event in events if event.event_type == "validation_completed"
        ]
        if len(patch_events) != 1 or len(validation_events) != 1:
            raise ValueError("Task 3 requires exactly one Patch and Validation event")
        patch_event = patch_events[0]
        validation_event = validation_events[0]
        supported_sequence = h2_assessments[0].sequence
        if not (
            reformulation.sequence
            < supported_sequence
            < patch_event.sequence
            < validation_event.sequence
        ):
            raise ValueError("invalid Reformulation, support, Patch, Validation order")
        for event in (patch_event, validation_event):
            if [
                (item.hypothesis_id, item.status)
                for item in event.hypothesis_history
            ] != [("H1", "rejected"), ("H2", "supported")]:
                raise ValueError("Patch and Validation require persisted supported H2")
        if (
            patch_event.patch != patch
            or patch_event.validation_action is None
            or patch_event.validation_action.hypothesis_id != "H2"
            or validation_event.patch != patch
            or validation_event.validation != validation
            or validation_event.validation_action is None
            or validation_event.validation_action.hypothesis_id != "H2"
        ):
            raise ValueError("Patch or Validation event is not bound to supported H2")
        persisted_validation = PublicValidationResult.model_validate_json(
            artifact_path(directory, validation.artifact_ref).read_text()
        )
        if persisted_validation != validation or not any(
            event.validation == validation for event in events
        ):
            raise ValueError("Validation differs from recorded artifacts")
        patch_text = artifact_path(directory, validation.patch_artifact_ref).read_text()
        if patch_text != patch.unified_diff.rstrip("\n") + "\n":
            raise ValueError("patch artifact mismatch")
        for check in (validation.static_check, validation.registered_test):
            if check is not None:
                artifact_path(directory, check.artifact_ref)
        result["repair_validation"] = validation.status
        result["trajectory_pass"] = True
        result["outcome_pass"] = bool(
            report.status == "completed"
            and report.stop_reason == "validation_passed"
            and validation.status == "passed"
        )
    except (
        OSError,
        ValueError,
        KeyError,
        IndexError,
        TypeError,
        DecisionValidationError,
    ) as exc:
        result["audit_error"] = str(exc)
        result["trajectory_pass"] = False
        result["outcome_pass"] = False
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_directory", type=Path)
    args = parser.parse_args(argv)
    result = check_task_3_run(args.run_directory)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["trajectory_pass"] and result["outcome_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
