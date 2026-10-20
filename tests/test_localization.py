from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from coderca.contracts import ReportDecision


def test_legacy_normalization_never_fills_from_initial_hypothesis() -> None:
    from coderca.localization import normalize_legacy_report

    old = {
        "final_hypothesis": {"root_symbol": "Switch"},
        "root_cause_analysis": report_fields(),
    }
    migrated = normalize_legacy_report(old)
    assert migrated["root_cause_analysis"]["location"] is None
    assert old["root_cause_analysis"] == report_fields()


@pytest.mark.parametrize("tool", ["read_code", "inspect_diff", "search_code"])
def test_final_location_requires_actual_covering_code_evidence(
    tmp_path: Path, tool: str
) -> None:
    from coderca.benchmark import load_task_2_manifest, materialize_task_2
    from coderca.contracts import (
        DecisionValidationError,
        DiagnosisEvent,
        DiagnosisStage,
        Evidence,
        Experiment,
        FinalRootCauseLocation,
        Observation,
    )
    from coderca.localization import code_evidence_spans, validate_location_sources
    from coderca.tool_runtime import ToolRuntime

    manifest = load_task_2_manifest()
    workspace = materialize_task_2(tmp_path / "repo")
    runtime = ToolRuntime(workspace, manifest)
    arguments: dict[str, object] = {"path": "./waffle//utils.py"}
    if tool == "read_code":
        arguments.update(start_line=20, end_line=26)
    elif tool == "search_code":
        arguments.update(query="lower", search_kind="content")
    experiment = Experiment(
        experiment_id="X1",
        hypothesis_id="H1",
        tool_name=tool,
        purpose="Inspect the mechanism",
        expected_observation="normalization",
        falsification_relevance="No normalization opposes H1",
        arguments=arguments,
    )
    result = runtime.execute(experiment, artifact_directory=tmp_path / "tool-results")
    assert result.status == "success"
    observation = Observation(
        observation_id="O1",
        experiment_id="X1",
        hypothesis_id="H1",
        source=tool,
        summary="observed",
        artifact_ref=result.artifact_ref,
        tool_result_ref=result.tool_result_id,
        excerpt=result.output,
    )
    evidence = Evidence(
        evidence_id="E1",
        hypothesis_id="H1",
        observation_ref="O1",
        provenance=f"{tool}:{result.artifact_ref}",
        direction="supporting",
        explanation="Concrete normalization mechanism",
    )
    events = [
        DiagnosisEvent(
            sequence=1,
            event_type="tool_executed",
            run_id="run",
            task_id=manifest.task_id,
            stage=DiagnosisStage.EXECUTING_TOOL,
            message="executed",
            experiment=experiment,
            tool_result=result,
        ),
        DiagnosisEvent(
            sequence=2,
            event_type="evidence_recorded",
            run_id="run",
            task_id=manifest.task_id,
            stage=DiagnosisStage.UPDATING_EVIDENCE,
            message="recorded",
            observation=observation,
            evidence=evidence,
        ),
    ]
    location = FinalRootCauseLocation(
        path="waffle/utils.py",
        symbol="keyfmt",
        start_line=25,
        end_line=25,
        evidence_refs=("E1",),
    )

    def validate(
        candidate: FinalRootCauseLocation,
        hypothesis: str = "H1",
        evidence_basis: tuple[str, ...] = (),
    ) -> None:
        validate_location_sources(
            candidate,
            hypothesis,
            manifest,
            [evidence],
            [observation],
            events,
            tmp_path,
            evidence_basis=evidence_basis,
        )

    validate(location)
    assert code_evidence_spans("H1", [evidence], [observation], events, tmp_path)
    runtime.validate_location_range(location.path, 25, 25)
    for changes in (
        {"start_line": 1, "end_line": 2},
        {"path": "waffle/models.py"},
        {"evidence_refs": ("E9",)},
        {"path": "private/secret.py"},
    ):
        with pytest.raises(DecisionValidationError):
            validate(location.model_copy(update=changes))
    with pytest.raises(DecisionValidationError):
        validate(location, "H2")
    validate(location, "H2", ("E1",))
    assert code_evidence_spans(
        "H2",
        [evidence],
        [observation],
        events,
        tmp_path,
        evidence_basis=("E1",),
    )
    with pytest.raises(DecisionValidationError):
        validate(location, "H2", ("E9",))
    with pytest.raises(DecisionValidationError):
        runtime.validate_location_range(location.path, 1, 99999)
    (workspace / "waffle/link.py").symlink_to(workspace / location.path)
    with pytest.raises(DecisionValidationError):
        runtime.validate_location_range("waffle/link.py", 1, 1)
    (tmp_path / result.artifact_ref).unlink()
    with pytest.raises(DecisionValidationError):
        validate(location)


@pytest.mark.parametrize(
    ("search_kind", "query", "location_line", "truncate_match"),
    [
        ("path", "utils.py", 25, False),
        ("content", "CODERCA_QUERY_THAT_DOES_NOT_EXIST", 25, False),
        ("content", "def get_setting", 25, False),
        ("content", "lower", 25, True),
    ],
    ids=["path-search", "no-matches", "non-covering", "truncated-match"],
)
def test_final_location_rejects_non_qualifying_search_evidence(
    tmp_path: Path,
    search_kind: str,
    query: str,
    location_line: int,
    truncate_match: bool,
) -> None:
    import json

    from coderca.benchmark import load_task_2_manifest, materialize_task_2
    from coderca.contracts import (
        DecisionValidationError,
        DiagnosisEvent,
        DiagnosisStage,
        Evidence,
        Experiment,
        FinalRootCauseLocation,
        Observation,
    )
    from coderca.localization import validate_location_sources
    from coderca.tool_runtime import ToolRuntime

    manifest = load_task_2_manifest()
    workspace = materialize_task_2(tmp_path / "repo")
    runtime = ToolRuntime(workspace, manifest)
    experiment = Experiment(
        experiment_id="X1",
        hypothesis_id="H1",
        tool_name="search_code",
        purpose="Find a candidate source location",
        expected_observation="A bounded repository match",
        falsification_relevance="An exact match can expose relevant code",
        arguments={
            "path": "waffle/utils.py",
            "query": query,
            "search_kind": search_kind,
        },
    )
    result = runtime.execute(experiment, artifact_directory=tmp_path / "tool-results")
    assert result.status == "success"
    if truncate_match:
        artifact = tmp_path / result.artifact_ref
        payload = json.loads(artifact.read_text())
        assert payload["matches"]
        payload["matches"][0]["truncated"] = True
        serialized = json.dumps(payload, sort_keys=True)
        artifact.write_text(serialized)
        result = result.model_copy(update={"output": serialized})
    observation = Observation(
        observation_id="O1",
        experiment_id="X1",
        hypothesis_id="H1",
        source="search_code",
        summary="searched",
        artifact_ref=result.artifact_ref,
        tool_result_ref=result.tool_result_id,
        excerpt=result.output,
    )
    evidence = Evidence(
        evidence_id="E1",
        hypothesis_id="H1",
        observation_ref="O1",
        provenance=f"search_code:{result.artifact_ref}",
        direction="supporting",
        explanation="The search result identifies a candidate location.",
    )
    events = [
        DiagnosisEvent(
            sequence=1,
            event_type="tool_executed",
            run_id="run",
            task_id=manifest.task_id,
            stage=DiagnosisStage.EXECUTING_TOOL,
            message="executed",
            experiment=experiment,
            tool_result=result,
        ),
        DiagnosisEvent(
            sequence=2,
            event_type="evidence_recorded",
            run_id="run",
            task_id=manifest.task_id,
            stage=DiagnosisStage.UPDATING_EVIDENCE,
            message="recorded",
            observation=observation,
            evidence=evidence,
        ),
    ]
    location = FinalRootCauseLocation(
        path="waffle/utils.py",
        symbol="keyfmt",
        start_line=location_line,
        end_line=location_line,
        evidence_refs=("E1",),
    )

    with pytest.raises(DecisionValidationError):
        validate_location_sources(
            location,
            "H1",
            manifest,
            [evidence],
            [observation],
            events,
            tmp_path,
        )


def report_fields() -> dict[str, object]:
    return dict(
        trigger_condition="trigger",
        propagation_path="path",
        failure_manifestation="failure",
        repair_recommendation="repair",
    )


def test_new_report_requires_explicit_nullable_location() -> None:
    assert "location" in ReportDecision.model_fields
    with pytest.raises(ValidationError):
        ReportDecision.model_validate(report_fields())
    assert (
        ReportDecision.model_validate({**report_fields(), "location": None}).location
        is None
    )


@pytest.mark.parametrize(
    "update",
    [
        {"start_line": 0},
        {"end_line": 1},
        {"path": "../outside.py"},
        {"path": "/outside.py"},
        {"evidence_refs": []},
        {"evidence_refs": ["E1", "E1"]},
    ],
)
def test_location_rejects_invalid_structure(update: dict[str, object]) -> None:
    from coderca.contracts import FinalRootCauseLocation

    data = dict(
        path="src/code.py",
        symbol="helper",
        start_line=2,
        end_line=3,
        evidence_refs=["E1"],
    )
    with pytest.raises(ValidationError):
        FinalRootCauseLocation.model_validate({**data, **update})
