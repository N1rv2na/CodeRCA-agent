from __future__ import annotations

import json
from importlib.util import find_spec
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from coderca import model_gate
from coderca.model_provider import (
    FakeModelProvider,
    ModelConfiguration,
    ModelProviderError,
    StructuredModelResponse,
    load_model_environment,
)

GateResponse = TypeVar("GateResponse", bound=BaseModel)


def test_model_compatibility_gate_module_exists() -> None:
    assert find_spec("coderca.model_gate") is not None


def model_configuration() -> ModelConfiguration:
    configuration, _ = load_model_environment(
        {
            "CODERCA_MODEL_BASE_URL": "https://models.example/private/account/v1",
            "CODERCA_MODEL_ID": "example-model",
            "CODERCA_MODEL_API_KEY": "secret-key",
        }
    )
    return configuration


def test_successful_gate_runs_each_probe_once_and_writes_a_redacted_report(
    tmp_path: Path,
    valid_model_gate_responses: dict[str, dict[str, object]],
) -> None:
    assert hasattr(model_gate, "run_model_compatibility_gate")
    provider = FakeModelProvider(valid_model_gate_responses)

    report = model_gate.run_model_compatibility_gate(
        provider=provider,
        configuration=model_configuration(),
        output_directory=tmp_path / "gate",
    )

    assert provider.structured_calls == [
        "preflight",
        "stage_schema",
        "tool_arguments",
        "evidence_update",
        "python_patch",
    ]
    assert report.compatible is True
    assert report.failure_category is None
    assert report.model_id == "example-model"
    assert report.endpoint == "https://models.example"
    assert report.request_configuration.model_dump() == {
        "stream": False,
        "temperature": 0,
        "response_format_type": "json_schema",
        "strict": True,
    }
    assert [probe.status for probe in report.probes] == ["passed"] * 5
    assert len({probe.name for probe in report.probes}) == 5
    assert all(probe.original_response_artifact for probe in report.probes)

    report_path = tmp_path / "gate" / "model-gate.json"
    assert report_path.is_file()
    serialized = report_path.read_text()
    assert json.loads(serialized) == report.model_dump(mode="json")
    assert "secret-key" not in serialized
    assert "private/account" not in serialized
    for probe in report.probes:
        artifact_path = (
            tmp_path / "gate" / str(probe.original_response_artifact)
        )
        assert artifact_path.is_file()
        assert "secret-key" not in artifact_path.read_text()


def test_gate_stops_after_a_provider_failure_and_records_no_authorization_state(
    tmp_path: Path,
    valid_model_gate_responses: dict[str, dict[str, object]],
) -> None:
    class FailingProvider(FakeModelProvider):
        def generate_structured(
            self,
            *,
            schema_name: str,
            system_prompt: str,
            user_prompt: str,
            response_model: type[GateResponse],
        ) -> StructuredModelResponse[GateResponse]:
            if schema_name == "tool_arguments":
                self.structured_calls.append(schema_name)
                raise ModelProviderError(
                    "timeout", "The model request exceeded its timeout."
                )
            return super().generate_structured(
                schema_name=schema_name,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=response_model,
            )

    provider = FailingProvider(valid_model_gate_responses)
    output_directory = tmp_path / "gate"

    report = model_gate.run_model_compatibility_gate(
        provider=provider,
        configuration=model_configuration(),
        output_directory=output_directory,
    )

    assert provider.structured_calls == [
        "preflight",
        "stage_schema",
        "tool_arguments",
    ]
    assert report.compatible is False
    assert report.failure_category == "timeout"
    assert report.probes[-1].model_dump() == {
        "name": "tool_arguments",
        "status": "failed",
        "failure_category": "timeout",
        "original_response_artifact": None,
    }
    report_payload = json.loads(
        (output_directory / "model-gate.json").read_text()
    )
    assert "authorized" not in report_payload
    assert "authorization" not in report_payload
    assert not (tmp_path / ".coderca-runs").exists()


def test_gate_rejects_a_patch_that_does_not_apply_to_the_probe_fixture(
    tmp_path: Path,
    valid_model_gate_responses: dict[str, dict[str, object]],
) -> None:
    responses = valid_model_gate_responses
    responses["python_patch"]["unified_diff"] = (
        "--- a/sample.py\n"
        "+++ b/sample.py\n"
        "@@ -1,1 +1,1 @@\n"
        "-not the source line\n"
        "+still not applicable\n"
    )
    provider = FakeModelProvider(responses)

    report = model_gate.run_model_compatibility_gate(
        provider=provider,
        configuration=model_configuration(),
        output_directory=tmp_path / "gate",
    )

    assert len(provider.structured_calls) == 5
    assert report.compatible is False
    assert report.failure_category == "patch_not_applicable"
    assert report.probes[-1].status == "failed"
    assert report.probes[-1].original_response_artifact == (
        "responses/python_patch.json"
    )


def test_gate_accepts_an_applicable_syntax_valid_equivalent_patch(
    tmp_path: Path,
    valid_model_gate_responses: dict[str, dict[str, object]],
) -> None:
    responses = valid_model_gate_responses
    responses["python_patch"]["unified_diff"] = (
        "--- a/sample.py\n"
        "+++ b/sample.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def select_timeout(configured: int | None, default: int) -> int:\n"
        "-    return configured or default\n"
        "+    return default if configured is None else configured\n"
    )
    provider = FakeModelProvider(responses)

    report = model_gate.run_model_compatibility_gate(
        provider=provider,
        configuration=model_configuration(),
        output_directory=tmp_path / "gate",
    )

    assert report.compatible is True
    assert report.failure_category is None


def test_gate_accepts_a_correct_patch_with_sequential_control_flow(
    tmp_path: Path,
    valid_model_gate_responses: dict[str, dict[str, object]],
) -> None:
    responses = valid_model_gate_responses
    responses["python_patch"]["unified_diff"] = (
        "--- a/sample.py\n"
        "+++ b/sample.py\n"
        "@@ -1,2 +1,4 @@\n"
        " def select_timeout(configured: int | None, default: int) -> int:\n"
        "-    return configured or default\n"
        "+    if configured is None:\n"
        "+        return default\n"
        "+    return configured\n"
    )

    report = model_gate.run_model_compatibility_gate(
        provider=FakeModelProvider(responses),
        configuration=model_configuration(),
        output_directory=tmp_path / "gate",
    )

    assert report.compatible is True


def test_gate_rejects_an_applicable_patch_that_breaks_required_behavior(
    tmp_path: Path,
    valid_model_gate_responses: dict[str, dict[str, object]],
) -> None:
    responses = valid_model_gate_responses
    responses["python_patch"]["unified_diff"] = (
        "--- a/sample.py\n"
        "+++ b/sample.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def select_timeout(configured: int | None, default: int) -> int:\n"
        "-    return configured or default\n"
        "+    return default\n"
    )

    report = model_gate.run_model_compatibility_gate(
        provider=FakeModelProvider(responses),
        configuration=model_configuration(),
        output_directory=tmp_path / "gate",
    )

    assert report.compatible is False
    assert report.failure_category == "patch_not_applicable"


def test_gate_retains_sanitized_original_response_for_failed_probe(
    tmp_path: Path,
    valid_model_gate_responses: dict[str, dict[str, object]],
) -> None:
    class FailingProvider(FakeModelProvider):
        def generate_structured(
            self,
            *,
            schema_name: str,
            system_prompt: str,
            user_prompt: str,
            response_model: type[GateResponse],
        ) -> StructuredModelResponse[GateResponse]:
            raise ModelProviderError(
                "schema_mismatch",
                "The response failed validation.",
                original_response={"choices": [], "credential": "[REDACTED]"},
            )

    output_directory = tmp_path / "gate"
    report = model_gate.run_model_compatibility_gate(
        provider=FailingProvider(valid_model_gate_responses),
        configuration=model_configuration(),
        output_directory=output_directory,
    )

    artifact_reference = report.probes[0].original_response_artifact
    assert artifact_reference == "responses/preflight.json"
    assert json.loads((output_directory / artifact_reference).read_text()) == {
        "choices": [],
        "credential": "[REDACTED]",
    }


def test_gate_records_invalid_tool_arguments_as_a_schema_failure(
    tmp_path: Path,
    valid_model_gate_responses: dict[str, dict[str, object]],
) -> None:
    responses = valid_model_gate_responses
    arguments = responses["tool_arguments"]["arguments"]
    assert isinstance(arguments, dict)
    arguments["path"] = "../secrets.txt"
    provider = FakeModelProvider(responses)

    report = model_gate.run_model_compatibility_gate(
        provider=provider,
        configuration=model_configuration(),
        output_directory=tmp_path / "gate",
    )

    assert provider.structured_calls == [
        "preflight",
        "stage_schema",
        "tool_arguments",
    ]
    assert report.compatible is False
    assert report.failure_category == "schema_mismatch"
    assert report.probes[-1].failure_category == "schema_mismatch"
