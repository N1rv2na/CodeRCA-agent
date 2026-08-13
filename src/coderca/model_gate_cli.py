"""Explicit command-line entry point for the Gemini compatibility gate."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .model_provider import GEMINI_API_KEY_ENV, GeminiModelProvider


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not os.environ.get(GEMINI_API_KEY_ENV):
        print(
            json.dumps(
                {
                    "compatible": False,
                    "failure_category": "missing_credentials",
                },
                sort_keys=True,
            )
        )
        return 3
    provider = GeminiModelProvider()
    result = provider.run_compatibility_gate(Path(args.output_directory))
    print(
        json.dumps(
            {
                "compatible": result.compatible,
                "failure_category": result.failure_category,
                "model": result.model,
                "artifact_manifest": str(result.artifact_manifest),
            },
            sort_keys=True,
        )
    )
    return 0 if result.compatible else 3


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="coderca-model-gate")
    parser.add_argument(
        "--output-directory",
        default=".coderca-model-gate",
        help="directory for redacted compatibility artifacts",
    )
    return parser


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
