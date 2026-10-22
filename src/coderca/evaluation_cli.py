"""CLI for deterministic Engineering Evaluation of persisted Diagnosis Runs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from pydantic import ValidationError

from .evaluation import CausalReviewRecord, evaluate_suite


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        reviews = _load_reviews(tuple(Path(value) for value in args.causal_review))
        result = evaluate_suite(
            tuple(Path(value) for value in args.run_directory),
            causal_reviews=reviews,
        )
    except (OSError, ValueError, ValidationError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {
                    "error": {
                        "code": "evaluation_input_error",
                        "message": str(exc),
                    }
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(result.model_dump_json(indent=2))
    return 0 if result.tasks and all(item.accepted for item in result.tasks) else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="coderca-evaluate")
    parser.add_argument(
        "--run-directory",
        action="append",
        required=True,
        help="persisted Diagnosis Run directory; repeat once per frozen task",
    )
    parser.add_argument(
        "--causal-review",
        action="append",
        default=[],
        help="CausalReviewRecord JSON file; repeat once per reviewed task",
    )
    return parser


def _load_reviews(paths: tuple[Path, ...]) -> dict[str, CausalReviewRecord]:
    reviews: dict[str, CausalReviewRecord] = {}
    for path in paths:
        review = CausalReviewRecord.model_validate_json(path.read_text())
        if review.task_id in reviews:
            raise ValueError(f"duplicate Causal Review task: {review.task_id}")
        reviews[review.task_id] = review
    return reviews


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
