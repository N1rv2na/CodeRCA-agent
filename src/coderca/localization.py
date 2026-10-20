"""Final-location provenance and read-only compatibility for persisted reports."""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

from .contracts import (
    DecisionValidationError,
    DiagnosisEvent,
    DiagnosisReport,
    Evidence,
    FinalRootCauseLocation,
    Observation,
    PublicValidationResult,
    TaskManifest,
)
from .tool_runtime import SearchCodeResult


def normalize_legacy_report(value: dict[str, Any]) -> dict[str, Any]:
    """Only persisted report/event readers may use this; never model responses."""
    value = copy.deepcopy(value)
    analysis = value.get("root_cause_analysis")
    if isinstance(analysis, dict):
        analysis.setdefault("location", None)
    return value


def read_persisted_report(value: dict[str, Any]) -> DiagnosisReport:
    return DiagnosisReport.model_validate(normalize_legacy_report(value))


def artifact_path(directory: Path, ref: str) -> Path:
    root = directory.resolve()
    path = (root / ref).resolve()
    if Path(ref).is_absolute() or not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f"missing or out-of-bound artifact: {ref}")
    return path


def audit_evidence(
    evidence: Evidence,
    observations: list[Observation],
    events: list[DiagnosisEvent],
    directory: Path,
) -> tuple[Observation, DiagnosisEvent, str]:
    observations_found = [
        o for o in observations if o.observation_id == evidence.observation_ref
    ]
    if len(observations_found) != 1:
        raise ValueError("Evidence must resolve one Observation")
    observation = observations_found[0]
    if observation.hypothesis_id != evidence.hypothesis_id:
        raise ValueError("Evidence/Observation Hypothesis mismatch")
    if evidence.provenance != f"{observation.source}:{observation.artifact_ref}":
        raise ValueError("Evidence provenance mismatch")
    if not any(e.evidence == evidence and e.observation == observation for e in events):
        raise ValueError("Evidence/Observation does not match recorded event")
    matches = [
        e
        for e in events
        if e.tool_result and e.tool_result.tool_result_id == observation.tool_result_ref
    ]
    if len(matches) != 1:
        raise ValueError("Observation must resolve one Tool Result")
    event = matches[0]
    result, experiment = event.tool_result, event.experiment
    assert result is not None
    if observation.source == "public_validation":
        action, validation = event.validation_action, event.validation
        if (
            action is None
            or validation is None
            or action.hypothesis_id != evidence.hypothesis_id
            or result.hypothesis_id != evidence.hypothesis_id
            or validation.hypothesis_id != evidence.hypothesis_id
            or action.tool_name != "apply_patch"
            or result.tool_name != "apply_patch"
            or action.validation_action_id != observation.validation_action_id
            or result.validation_action_id != observation.validation_action_id
            or result.artifact_ref != observation.artifact_ref
            or validation.artifact_ref != observation.artifact_ref
        ):
            raise ValueError("broken Public Validation Evidence binding")
        content = artifact_path(directory, observation.artifact_ref).read_text()
        if PublicValidationResult.model_validate_json(content) != validation:
            raise ValueError("Public Validation artifact differs from recorded event")
        return observation, event, content
    if (
        result.status != "success"
        or result.hypothesis_id != evidence.hypothesis_id
        or result.tool_name != observation.source
        or result.artifact_ref != observation.artifact_ref
        or not experiment
        or experiment.hypothesis_id != evidence.hypothesis_id
        or experiment.experiment_id != observation.experiment_id
        or result.experiment_id != experiment.experiment_id
        or experiment.tool_name != result.tool_name
    ):
        raise ValueError("broken Experiment/Tool Result/Observation binding")
    content = artifact_path(directory, observation.artifact_ref).read_text()
    if observation.source == "search_code":
        full_search = SearchCodeResult.model_validate_json(content)
        recorded_search = SearchCodeResult.model_validate_json(result.output)
        if (
            full_search.query != recorded_search.query
            or full_search.search_kind != recorded_search.search_kind
            or full_search.path != recorded_search.path
            or full_search.status != recorded_search.status
            or any(
                match not in full_search.matches for match in recorded_search.matches
            )
        ):
            raise ValueError("search artifact differs from recorded Tool Result")
    elif observation.source in {"read_code", "inspect_diff"} and not content.startswith(
        result.output
    ):
        raise ValueError("code artifact differs from recorded Tool Result")
    return observation, event, content


def _ranges(
    content: str, tool: str, arguments: dict[str, Any]
) -> list[tuple[str, int, int]]:
    """Extract only observed source coordinates, never infer symbols from text."""
    points: list[tuple[str, int]] = []
    path = arguments.get("path")
    if tool == "read_code" and path:
        for line in content.splitlines():
            match = re.match(r"^(\d+): ", line)
            if match:
                points.append((Path(path).as_posix(), int(match[1])))
    elif tool == "inspect_diff":
        current: str | None = None
        number: int | None = None
        remaining = 0
        for line in content.splitlines():
            if line.startswith("diff --git "):
                current, number = None, None
                remaining = 0
            elif line.startswith("+++ "):
                current = line[6:] if line.startswith("+++ b/") else None
            elif line.startswith("@@ "):
                match = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", line)
                number = int(match[1]) if match else None
                remaining = int(match[2] or 1) if match else 0
            elif (
                current and number is not None and remaining and line[:1] in {" ", "+"}
            ):
                points.append((current, number))
                number += 1
                remaining -= 1
    elif tool == "search_code":
        result = SearchCodeResult.model_validate_json(content)
        if (
            result.search_kind != "content"
            or result.status != "matched"
            or result.query != arguments.get("query")
            or result.path != path
        ):
            return []
        return [
            (Path(match.path).as_posix(), match.start_line, match.end_line)
            for match in result.matches
            if not match.truncated
            and match.start_line is not None
            and match.end_line is not None
            and match.start_line <= match.end_line
        ]
    ranges: list[tuple[str, int, int]] = []
    for name, number in points:
        if ranges and ranges[-1][0] == name and ranges[-1][2] + 1 == number:
            ranges[-1] = (name, ranges[-1][1], number)
        else:
            ranges.append((name, number, number))
    return ranges


def code_evidence_spans(
    hypothesis_id: str,
    evidence: list[Evidence],
    observations: list[Observation],
    events: list[DiagnosisEvent],
    directory: Path,
    *,
    evidence_basis: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    eligible_ids = {
        entry.evidence_id
        for entry in evidence
        if entry.hypothesis_id == hypothesis_id
    } | set(evidence_basis)
    for entry in evidence:
        if entry.evidence_id not in eligible_ids:
            continue
        observation = next(
            (o for o in observations if o.observation_id == entry.observation_ref), None
        )
        if observation is None or observation.source not in {
            "read_code",
            "inspect_diff",
            "search_code",
        }:
            continue
        observation, event, content = audit_evidence(
            entry, observations, events, directory
        )
        assert event.experiment is not None
        arguments = event.experiment.arguments
        for path, start, end in _ranges(content, observation.source, arguments):
            if observation.source == "read_code":
                args = event.experiment.arguments
                if start < args["start_line"] or end > args["end_line"]:
                    raise ValueError(
                        "read_code output exceeds registered request range"
                    )
            spans.append(
                dict(
                    evidence_id=entry.evidence_id,
                    observation_ref=observation.observation_id,
                    path=path,
                    start_line=start,
                    end_line=end,
                    artifact_ref=observation.artifact_ref,
                )
            )
    return spans


def validate_location_sources(
    location: FinalRootCauseLocation | None,
    hypothesis_id: str,
    manifest: TaskManifest,
    evidence: list[Evidence],
    observations: list[Observation],
    events: list[DiagnosisEvent],
    directory: Path,
    *,
    evidence_basis: tuple[str, ...] = (),
) -> None:
    if location is None:
        return
    try:
        if not any(
            location.path == p.rstrip("/")
            or location.path.startswith(p.rstrip("/") + "/")
            for p in manifest.read_paths
        ):
            raise ValueError("location outside read_paths")
        refs = {e.evidence_id: e for e in evidence}
        eligible_ids = {
            entry.evidence_id
            for entry in evidence
            if entry.hypothesis_id == hypothesis_id
        } | set(evidence_basis)
        for ref in location.evidence_refs:
            if ref not in refs or ref not in eligible_ids:
                raise ValueError(
                    "location Evidence must belong to the supported Hypothesis "
                    "or its explicit Evidence Basis"
                )
            audit_evidence(refs[ref], observations, events, directory)
        spans = code_evidence_spans(
            hypothesis_id,
            evidence,
            observations,
            events,
            directory,
            evidence_basis=evidence_basis,
        )
        if not any(
            s["evidence_id"] in location.evidence_refs
            and s["path"] == location.path
            and s["start_line"]
            <= location.start_line
            <= location.end_line
            <= s["end_line"]
            for s in spans
        ):
            raise ValueError(
                "location requires covering read_code, diff, "
                "or exact content-search Evidence"
            )
    except (ValueError, OSError, KeyError, TypeError) as exc:
        raise DecisionValidationError(
            "invalid final location",
            [
                {
                    "loc": ["location"],
                    "type": "invalid_location_provenance",
                    "msg": str(exc),
                }
            ],
        ) from exc
