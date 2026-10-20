"""Author-only Task 2 Outcome and Search checks; causal review remains manual."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from .benchmark import load_task_2_manifest
from .contracts import (
    DiagnosisEvent,
    HypothesisAssessmentDecision,
    PublicValidationResult,
)
from .localization import (
    artifact_path,
    audit_evidence,
    normalize_legacy_report,
    read_persisted_report,
    validate_location_sources,
)
from .tool_runtime import SearchCodeResult

# Author-owned expectations, never sent to the model or used to fill its report.
_ROOT_PATH = "waffle/utils.py"
_ROOT_SYMBOLS = {"keyfmt", "waffle.utils.keyfmt"}
_DEFECT_LINE = 25


def check_task_2_run(directory: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "location": "not_provided",
        "repair_validation": "not_run",
        "causal_review": "required",
        "search_capability": "not_demonstrated",
        "outcome_pass": False,
        "human_review_required": True,
        "audit_error": None,
    }
    try:
        report = read_persisted_report(
            json.loads(artifact_path(directory, "report.json").read_text())
        )
        events = [
            DiagnosisEvent.model_validate(normalize_legacy_report(json.loads(line)))
            for line in artifact_path(directory, "events.jsonl")
            .read_text()
            .splitlines()
            if line.strip()
        ]
        manifest = load_task_2_manifest()
        if json.loads(
            artifact_path(directory, "manifest.json").read_text()
        ) != manifest.model_dump(mode="json"):
            raise ValueError("Run Manifest is not frozen Task 2")
        if report.task_id != manifest.task_id or any(
            e.run_id != report.run_id or e.task_id != report.task_id for e in events
        ):
            raise ValueError("inconsistent Run identity")
        if [e.sequence for e in events] != list(range(1, len(events) + 1)):
            raise ValueError("invalid event sequence")
        if len({e.evidence_id for e in report.evidence}) != len(report.evidence):
            raise ValueError("duplicate Evidence ID")
        final = report.final_hypothesis
        if final and final not in report.hypothesis_history:
            raise ValueError("final Hypothesis absent from history")
        analysis = report.root_cause_analysis
        if analysis and analysis.location:
            if not final or final.status != "supported":
                raise ValueError("final location requires supported Hypothesis")
            validate_location_sources(
                analysis.location,
                final.hypothesis_id,
                manifest,
                report.evidence,
                report.observations,
                events,
                directory,
                evidence_basis=final.evidence_basis,
            )
            location = analysis.location
            result["location"] = (
                "hit"
                if (
                    location.path == _ROOT_PATH
                    and location.symbol in _ROOT_SYMBOLS
                    and location.start_line <= _DEFECT_LINE <= location.end_line
                )
                else "miss"
            )
        if report.validation:
            validation = report.validation
            if not final or validation.hypothesis_id != final.hypothesis_id:
                raise ValueError("Validation does not bind final Hypothesis")
            persisted = PublicValidationResult.model_validate_json(
                artifact_path(directory, validation.artifact_ref).read_text()
            )
            if persisted != validation or not any(
                e.validation == validation for e in events
            ):
                raise ValueError("Validation differs from recorded artifacts")
            patch_text = artifact_path(
                directory, validation.patch_artifact_ref
            ).read_text()
            if not report.patch or report.patch.hypothesis_id != final.hypothesis_id:
                raise ValueError("missing or wrongly bound patch")
            if patch_text != report.patch.unified_diff.rstrip("\n") + "\n":
                raise ValueError("patch artifact mismatch")
            for check in (validation.static_check, validation.registered_test):
                if check:
                    artifact_path(directory, check.artifact_ref)
            result["repair_validation"] = validation.status

        used: set[str] = set()
        for hypothesis in report.hypothesis_history:
            used.update(hypothesis.evidence_basis)
        if analysis and analysis.location:
            used.update(analysis.location.evidence_refs)
        for event in events:
            if event.event_type != "hypothesis_assessed":
                continue
            if not event.model_response_artifact:
                raise ValueError("assessment missing response artifact")
            raw = json.loads(
                artifact_path(directory, event.model_response_artifact).read_text()
            )
            if isinstance(raw, dict) and "choices" in raw:
                raw = json.loads(raw["choices"][0]["message"]["content"])
            used.update(HypothesisAssessmentDecision.model_validate(raw).evidence_refs)
        if not used.issubset({e.evidence_id for e in report.evidence}):
            raise ValueError("decision references missing Evidence")
        for evidence in report.evidence:
            observation, _, content = audit_evidence(
                evidence, report.observations, events, directory
            )
            if observation.source == "search_code":
                search = SearchCodeResult.model_validate_json(content)
                if (
                    search.status == "matched"
                    and search.matches
                    and evidence.evidence_id in used
                ):
                    result["search_capability"] = "verified"
        for observation in report.observations:
            artifact_path(directory, observation.artifact_ref)
        result["outcome_pass"] = bool(
            report.status == "completed"
            and final
            and final.status == "supported"
            and result["location"] == "hit"
            and result["repair_validation"] == "passed"
            and analysis
        )
    except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
        result["audit_error"] = str(exc)
        result["search_capability"] = "invalid_trajectory"
        result["outcome_pass"] = False
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_directory", type=Path)
    parser.add_argument(
        "--require-search",
        action="store_true",
        help="Additionally require demonstrated search contribution",
    )
    args = parser.parse_args(argv)
    result = check_task_2_run(args.run_directory)
    print(json.dumps(result, sort_keys=True))
    passed = result["outcome_pass"] and not result["audit_error"]
    if args.require_search:
        passed = passed and result["search_capability"] == "verified"
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
