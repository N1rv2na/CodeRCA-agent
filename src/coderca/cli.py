"""Non-interactive command-line adapter for the application service."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from pydantic import ValidationError

from .application import DiagnosisApplicationService
from .contracts import CliError, StructuredError, TaskManifest
from .model_provider import FakeModelProvider
from .run_store import RunStore


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    manifest_path = Path(args.manifest)
    try:
        raw_manifest = manifest_path.read_text(encoding="utf-8")
        manifest = TaskManifest.model_validate_json(raw_manifest)
    except ValidationError as exc:
        _write_error(
            StructuredError(
                code="invalid_manifest",
                message="Manifest does not satisfy the Task Manifest contract.",
                details=_json_safe(exc.errors()),
            )
        )
        return 2
    except (OSError, UnicodeError) as exc:
        _write_error(
            StructuredError(
                code="manifest_read_error",
                message="Manifest could not be read.",
                details={"path": str(manifest_path), "reason": str(exc)},
            )
        )
        return 2

    service = DiagnosisApplicationService(
        provider=FakeModelProvider(), run_store=RunStore(Path(args.runs_dir))
    )
    result = service.start_diagnosis(manifest)
    summary = {
        "run_id": result.run_id,
        "task_id": result.task_id,
        "stage": result.stage,
        "status": result.status,
        "stop_reason": result.stop_reason,
        "summary": result.summary,
        "run_directory": str(result.run_directory),
    }
    print(json.dumps(summary, sort_keys=True))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="coderca")
    parser.add_argument("manifest", type=str, help="path to a Task Manifest JSON file")
    parser.add_argument(
        "--runs-dir",
        default=".coderca-runs",
        help="directory in which Diagnosis Run directories are created",
    )
    return parser


def _write_error(error: StructuredError) -> None:
    payload = CliError(error=error).model_dump(mode="json")
    print(json.dumps(payload, sort_keys=True), file=sys.stderr)


def _json_safe(value: object) -> object:
    return json.loads(json.dumps(value, default=str))
