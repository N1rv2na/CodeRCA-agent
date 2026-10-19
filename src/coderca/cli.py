"""Non-interactive command-line adapter for the application service."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Mapping, Protocol, Sequence

from pydantic import SecretStr, ValidationError

from .application import DiagnosisApplicationService
from .context_builder import resolve_task_context
from .contracts import CliError, StructuredError, TaskManifest
from .model_provider import (
    FakeModelProvider,
    ModelConfiguration,
    ModelProviderError,
    OpenAICompatibleModelProvider,
    StructuredModelProvider,
    load_model_environment,
)
from .run_store import RunStore
from .tool_runtime import ToolRuntime, load_registered_test_command


class ProviderFactory(Protocol):
    def __call__(
        self, configuration: ModelConfiguration, api_key: SecretStr
    ) -> StructuredModelProvider:
        """Build the explicitly configured real ModelProvider."""


def main(
    argv: Sequence[str] | None = None,
    *,
    provider: StructuredModelProvider | None = None,
    environment: Mapping[str, str] | None = None,
    provider_factory: ProviderFactory | None = None,
) -> int:
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

    try:
        task = resolve_task_context(manifest, manifest_path.parent)
    except (OSError, UnicodeError, ValueError) as exc:
        _write_error(
            StructuredError(
                code="task_input_error",
                message="Diagnosis Task artifacts could not be resolved.",
                details={"path": manifest.ci_log, "reason": str(exc)},
            )
        )
        return 2

    selected_provider = provider
    if selected_provider is None and args.model_provider == "openai-compatible":
        try:
            configuration, api_key = load_model_environment(environment)
            factory = provider_factory or _default_provider_factory
            selected_provider = factory(configuration, api_key)
        except ModelProviderError as exc:
            _write_error(
                StructuredError(
                    code=exc.category,
                    message=str(exc),
                    details=exc.details,
                )
            )
            return 2
    if selected_provider is None:
        selected_provider = FakeModelProvider()

    tool_runtime = None
    if args.workspace is not None:
        if provider is None and args.model_provider == "fake":
            _write_error(
                StructuredError(
                    code="model_provider_required",
                    message=(
                        "The diagnosis loop requires an explicitly "
                        "configured ModelProvider."
                    ),
                    details={"model_provider": args.model_provider},
                )
            )
            return 2
        workspace = Path(args.workspace)
        if not workspace.is_dir():
            _write_error(
                StructuredError(
                    code="workspace_error",
                    message="Faulty Commit workspace is not a directory.",
                    details={"path": str(workspace)},
                )
            )
            return 2
        try:
            registered_test_command = load_registered_test_command(
                manifest_path.parent / "registered-command.json",
                expected_command_id=manifest.test_command_id,
            )
            tool_runtime = ToolRuntime(
                workspace,
                manifest,
                registered_test_command=registered_test_command,
            )
        except ValueError as exc:
            _write_error(
                StructuredError(
                    code="workspace_error",
                    message="Faulty Commit workspace failed validation.",
                    details={"path": str(workspace), "reason": str(exc)},
                )
            )
            return 2
    service = DiagnosisApplicationService(
        provider=selected_provider,
        run_store=RunStore(Path(args.runs_dir)),
        tool_runtime=tool_runtime,
    )
    result = service.start_diagnosis(task)
    summary = {
        "run_id": result.run_id,
        "task_id": result.task_id,
        "stage": result.stage,
        "status": result.status,
        "stop_reason": result.stop_reason,
        "summary": result.summary,
        "hypothesis_history": [
            hypothesis.model_dump(mode="json")
            for hypothesis in result.hypothesis_history
        ],
        "active_hypothesis": next(
            (
                hypothesis.model_dump(mode="json")
                for hypothesis in result.hypothesis_history
                if hypothesis.status in {"proposed", "testing"}
            ),
            None,
        ),
        "evidence_refs": [item.evidence_id for item in result.evidence],
        "run_directory": str(result.run_directory),
    }
    print(json.dumps(summary, sort_keys=True))
    return 0 if result.status != "failed" else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="coderca")
    parser.add_argument("manifest", type=str, help="path to a Task Manifest JSON file")
    parser.add_argument(
        "--runs-dir",
        default=".coderca-runs",
        help="directory in which Diagnosis Run directories are created",
    )
    parser.add_argument(
        "--model-provider",
        choices=("fake", "openai-compatible"),
        default="fake",
        help=(
            "model boundary to use; openai-compatible explicitly loads the "
            "CODERCA_MODEL_* environment"
        ),
    )
    parser.add_argument(
        "--workspace",
        help=(
            "prepared Faulty Commit workspace; when present, run the bounded "
            "diagnosis loop with registered tools"
        ),
    )
    return parser


def _default_provider_factory(
    configuration: ModelConfiguration, api_key: SecretStr
) -> OpenAICompatibleModelProvider:
    return OpenAICompatibleModelProvider(configuration, api_key)


def _write_error(error: StructuredError) -> None:
    payload = CliError(error=error).model_dump(mode="json")
    print(json.dumps(payload, sort_keys=True), file=sys.stderr)


def _json_safe(value: object) -> object:
    return json.loads(json.dumps(value, default=str))
