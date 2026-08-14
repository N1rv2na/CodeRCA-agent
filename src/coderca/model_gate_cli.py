"""Command-line entry point for the explicit Model Compatibility Gate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Mapping, Protocol, Sequence

from pydantic import SecretStr

from .contracts import CliError, StructuredError
from .model_gate import StructuredModelProvider, run_model_compatibility_gate
from .model_provider import (
    ModelConfiguration,
    ModelProviderError,
    OpenAICompatibleModelProvider,
    load_model_environment,
)


class ProviderFactory(Protocol):
    def __call__(
        self,
        configuration: ModelConfiguration,
        api_key: SecretStr,
        timeout_seconds: float,
    ) -> StructuredModelProvider:
        """Build the one provider used by this gate execution."""


def main(
    argv: Sequence[str] | None = None,
    *,
    environment: Mapping[str, str] | None = None,
    provider_factory: ProviderFactory | None = None,
) -> int:
    args = _build_parser().parse_args(argv)
    try:
        configuration, api_key = load_model_environment(environment)
    except ModelProviderError as exc:
        _write_error(
            StructuredError(
                code=exc.category,
                message=str(exc),
                details=exc.details,
            )
        )
        return 2

    factory = provider_factory or _default_provider_factory
    provider = factory(configuration, api_key, args.timeout_seconds)
    output_directory = Path(args.output_directory)
    try:
        report = run_model_compatibility_gate(
            provider=provider,
            configuration=configuration,
            output_directory=output_directory,
        )
    except OSError as exc:
        _write_error(
            StructuredError(
                code="artifact_write_error",
                message="Model Compatibility Report artifacts could not be written.",
                details={"reason": str(exc)},
            )
        )
        return 2

    print(
        json.dumps(
            {
                "compatible": report.compatible,
                "failure_category": report.failure_category,
                "model": report.model_id,
                "model_compatibility_report": str(output_directory / "model-gate.json"),
            },
            sort_keys=True,
        )
    )
    return 0 if report.compatible else 1


def _default_provider_factory(
    configuration: ModelConfiguration,
    api_key: SecretStr,
    timeout_seconds: float,
) -> OpenAICompatibleModelProvider:
    return OpenAICompatibleModelProvider(
        configuration, api_key, timeout_seconds=timeout_seconds
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="coderca-model-gate")
    parser.add_argument(
        "--output-directory",
        default=".coderca-model-gate",
        help="directory for the redacted compatibility report and probe artifacts",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=30,
        help="per-request timeout for the configured model endpoint",
    )
    return parser


def _write_error(error: StructuredError) -> None:
    payload = CliError(error=error).model_dump(mode="json")
    print(json.dumps(payload, sort_keys=True), file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
