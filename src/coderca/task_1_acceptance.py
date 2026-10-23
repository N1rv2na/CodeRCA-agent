"""Author-facing Task 1 checks over the canonical Engineering Evaluation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from .evaluation import evaluate_run, load_ground_truth


def check_task_1_run(directory: Path) -> dict[str, Any]:
    """Project the generic evaluator into a concise Task 1 acceptance result."""

    result: dict[str, Any] = {
        "audit_error": None,
        "candidate_patch": "not_run",
        "causal_review": "required",
        "human_review_required": True,
        "location": "not_provided",
        "outcome_pass": False,
        "patch_intent_compilation": "not_run",
        "repair_validation": "not_run",
        "report_contract": "failed",
        "trajectory_pass": False,
    }
    try:
        evaluated = evaluate_run(
            directory,
            load_ground_truth("crca-002-task-1"),
        )
        result.update(
            {
                "candidate_patch": evaluated.outcome.candidate_patch,
                "location": evaluated.outcome.location,
                "outcome_pass": evaluated.outcome.passed,
                "patch_intent_compilation": (
                    evaluated.outcome.patch_intent_compilation
                ),
                "repair_validation": evaluated.outcome.validation,
                "report_contract": evaluated.outcome.report_contract,
                "trajectory_pass": evaluated.trajectory.passed,
            }
        )
    except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
        result["audit_error"] = str(exc)
        result["outcome_pass"] = False
        result["trajectory_pass"] = False
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_directory", type=Path)
    args = parser.parse_args(argv)
    result = check_task_1_run(args.run_directory)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["outcome_pass"] and result["trajectory_pass"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
