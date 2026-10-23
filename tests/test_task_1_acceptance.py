from __future__ import annotations

from pathlib import Path
from typing import NoReturn

import pytest

from coderca.evaluation import (
    CausalReviewRecord,
    OutcomeEvaluation,
    TaskEvaluationResult,
    TrajectoryEvaluation,
)


def _evaluation(*, outcome: bool, trajectory: bool) -> TaskEvaluationResult:
    return TaskEvaluationResult(
        task_id="crca-002-task-1",
        run_id="run-1",
        run_directory="runs/run-1",
        outcome=OutcomeEvaluation(
            location="hit" if outcome else "miss",
            patch_intent_compilation="passed" if outcome else "failed",
            candidate_patch="applicable" if outcome else "invalid",
            validation="passed" if outcome else "failed",
            report_contract="passed",
            passed=outcome,
        ),
        trajectory=TrajectoryEvaluation(passed=trajectory),
        search_capability="not_demonstrated",
        causal_review=CausalReviewRecord.pending("crca-002-task-1"),
        accepted=False,
    )


def test_task_1_acceptance_projects_generic_evaluation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from coderca.task_1_acceptance import check_task_1_run

    monkeypatch.setattr(
        "coderca.task_1_acceptance.evaluate_run",
        lambda *_args, **_kwargs: _evaluation(outcome=True, trajectory=True),
    )

    assert check_task_1_run(Path("runs/run-1")) == {
        "audit_error": None,
        "candidate_patch": "applicable",
        "causal_review": "required",
        "human_review_required": True,
        "location": "hit",
        "outcome_pass": True,
        "patch_intent_compilation": "passed",
        "repair_validation": "passed",
        "report_contract": "passed",
        "trajectory_pass": True,
    }


def test_task_1_acceptance_maps_input_errors_to_audit_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from coderca.task_1_acceptance import check_task_1_run

    def fail(*_args: object, **_kwargs: object) -> NoReturn:
        raise ValueError("broken artifacts")

    monkeypatch.setattr("coderca.task_1_acceptance.evaluate_run", fail)

    checked = check_task_1_run(Path("runs/run-1"))
    assert checked["audit_error"] == "broken artifacts"
    assert checked["outcome_pass"] is False
    assert checked["trajectory_pass"] is False


def test_task_1_acceptance_cli_requires_automated_outcome_and_trajectory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from coderca.task_1_acceptance import main

    monkeypatch.setattr(
        "coderca.task_1_acceptance.evaluate_run",
        lambda *_args, **_kwargs: _evaluation(outcome=True, trajectory=True),
    )
    assert main(["runs/run-1"]) == 0

    monkeypatch.setattr(
        "coderca.task_1_acceptance.evaluate_run",
        lambda *_args, **_kwargs: _evaluation(outcome=True, trajectory=False),
    )
    assert main(["runs/run-1"]) == 1
