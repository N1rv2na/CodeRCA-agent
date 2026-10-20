from __future__ import annotations

import json
from importlib.util import find_spec
from pathlib import Path
from typing import TypeVar

import pytest
from pydantic import BaseModel

from coderca import model_gate
from coderca.contracts import HypothesisAssessmentDecision
from coderca.decision_prompts import HYPOTHESIS_ASSESSMENT_SYSTEM_PROMPT
from coderca.model_provider import (
    FakeModelProvider,
    ModelConfiguration,
    ModelProviderError,
    PersistenceSafeModelArtifact,
    StructuredModelResponse,
    StructuredOutputMode,
    load_model_environment,
)

GateResponse = TypeVar("GateResponse", bound=BaseModel)


def test_model_compatibility_gate_module_exists() -> None:
    assert find_spec("coderca.model_gate") is not None


def model_configuration(
    mode: str = "native_json_schema",
) -> ModelConfiguration:
    configuration, _ = load_model_environment(
        {
            "CODERCA_MODEL_BASE_URL": "https://models.example/private/account/v1",
            "CODERCA_MODEL_ID": "example-model",
            "CODERCA_MODEL_API_KEY": "secret-key",
            "CODERCA_MODEL_STRUCTURED_OUTPUT_MODE": mode,
        }
    )
    return configuration


@pytest.mark.parametrize(
    "mode",
    ["native_json_schema", "json_text"],
)
def test_successful_gate_runs_the_same_probes_and_records_mode(
    tmp_path: Path,
    valid_model_gate_responses: dict[str, dict[str, object]],
    mode: str,
) -> None:
    assert hasattr(model_gate, "run_model_compatibility_gate")
    provider = FakeModelProvider(valid_model_gate_responses)

    report = model_gate.run_model_compatibility_gate(
        provider=provider,
        configuration=model_configuration(mode),
        output_directory=tmp_path / "gate",
    )

    assert provider.structured_calls == [
        "preflight",
        "stage_schema",
        "tool_arguments",
        "evidence_update",
        "hypothesis_assessment",
        "python_patch_intent",
    ]
    assert report.compatible is True
    assert report.schema_version == "2"
    assert report.failure_category is None
    assert report.model_id == "example-model"
    assert report.structured_output_mode == StructuredOutputMode(mode)
    assert report.endpoint == "https://models.example"
    expected_request_configuration = {
        "stream": False,
        "temperature": 0,
        "response_format_type": (
            "json_schema" if mode == "native_json_schema" else None
        ),
        "strict": True if mode == "native_json_schema" else None,
    }
    assert report.request_configuration.model_dump() == expected_request_configuration
    assert [probe.status for probe in report.probes] == ["passed"] * 6
    assert len({probe.name for probe in report.probes}) == 6
    assert all(probe.original_response_artifact for probe in report.probes)

    report_path = tmp_path / "gate" / "model-gate.json"
    assert report_path.is_file()
    serialized = report_path.read_text()
    assert json.loads(serialized) == report.model_dump(mode="json")
    assert "secret-key" not in serialized
    assert "private/account" not in serialized
    assert f'"structured_output_mode": "{mode}"' in serialized
    for probe in report.probes:
        artifact_path = tmp_path / "gate" / str(probe.original_response_artifact)
        assert artifact_path.is_file()
        assert "secret-key" not in artifact_path.read_text()


def test_gate_uses_the_real_assessment_contract_and_shared_exact_prompt(
    tmp_path: Path,
    valid_model_gate_responses: dict[str, dict[str, object]],
) -> None:
    class InspectingProvider(FakeModelProvider):
        assessment_contract_seen = False

        def generate_structured(
            self,
            *,
            schema_name: str,
            system_prompt: str,
            user_prompt: str,
            response_model: type[GateResponse],
        ) -> StructuredModelResponse[GateResponse]:
            if schema_name == "hypothesis_assessment":
                assert response_model is HypothesisAssessmentDecision
                assert system_prompt == HYPOTHESIS_ASSESSMENT_SYSTEM_PROMPT
                self.assessment_contract_seen = True
            return super().generate_structured(
                schema_name=schema_name,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=response_model,
            )

    provider = InspectingProvider(valid_model_gate_responses)

    report = model_gate.run_model_compatibility_gate(
        provider=provider,
        configuration=model_configuration("json_text"),
        output_directory=tmp_path / "gate",
    )

    assert report.compatible is True
    assert provider.assessment_contract_seen is True


def test_gate_rejects_extra_assessment_fields_before_patch_probe(
    tmp_path: Path,
    valid_model_gate_responses: dict[str, dict[str, object]],
) -> None:
    valid_model_gate_responses["hypothesis_assessment"]["rationale_note"] = None
    provider = FakeModelProvider(valid_model_gate_responses)

    report = model_gate.run_model_compatibility_gate(
        provider=provider,
        configuration=model_configuration("json_text"),
        output_directory=tmp_path / "gate",
    )

    assert provider.structured_calls == [
        "preflight",
        "stage_schema",
        "tool_arguments",
        "evidence_update",
        "hypothesis_assessment",
    ]
    assert report.compatible is False
    assert report.failure_category == "schema_mismatch"
    assert report.probes[-1].name == "hypothesis_assessment"
    assert report.probes[-1].status == "failed"


def test_gate_report_does_not_persist_request_extension_values(
    tmp_path: Path,
    valid_model_gate_responses: dict[str, dict[str, object]],
) -> None:
    configuration, _ = load_model_environment(
        {
            "CODERCA_MODEL_BASE_URL": "https://models.example/v1",
            "CODERCA_MODEL_ID": "example-model",
            "CODERCA_MODEL_API_KEY": "secret-key",
            "CODERCA_MODEL_STRUCTURED_OUTPUT_MODE": "json_text",
            "CODERCA_MODEL_REQUEST_EXTENSIONS": (
                '{"private_endpoint_setting":"do-not-persist"}'
            ),
        }
    )

    report = model_gate.run_model_compatibility_gate(
        provider=FakeModelProvider(valid_model_gate_responses),
        configuration=configuration,
        output_directory=tmp_path / "gate",
    )

    serialized = report.model_dump_json()
    assert "private_endpoint_setting" not in serialized
    assert "do-not-persist" not in serialized


@pytest.mark.parametrize(
    "mode",
    ["native_json_schema", "json_text"],
)
def test_gate_stops_after_a_provider_failure_in_both_modes(
    tmp_path: Path,
    valid_model_gate_responses: dict[str, dict[str, object]],
    mode: str,
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
        configuration=model_configuration(mode),
        output_directory=output_directory,
    )

    assert provider.structured_calls == [
        "preflight",
        "stage_schema",
        "tool_arguments",
    ]
    assert report.compatible is False
    assert report.failure_category == "timeout"
    assert report.structured_output_mode.value == mode
    assert report.probes[-1].model_dump() == {
        "name": "tool_arguments",
        "status": "failed",
        "failure_category": "timeout",
        "original_response_artifact": None,
    }
    report_payload = json.loads((output_directory / "model-gate.json").read_text())
    assert "authorized" not in report_payload
    assert "authorization" not in report_payload
    assert not (tmp_path / ".coderca-runs").exists()


def test_gate_rejects_a_patch_intent_that_does_not_match_the_probe_fixture(
    tmp_path: Path,
    valid_model_gate_responses: dict[str, dict[str, object]],
) -> None:
    responses = valid_model_gate_responses
    responses["python_patch_intent"]["edits"] = [
        {"old_text": "not the source line", "new_text": "still not applicable"}
    ]
    provider = FakeModelProvider(responses)

    report = model_gate.run_model_compatibility_gate(
        provider=provider,
        configuration=model_configuration(),
        output_directory=tmp_path / "gate",
    )

    assert len(provider.structured_calls) == 6
    assert report.compatible is False
    assert report.failure_category == "patch_not_applicable"
    assert report.probes[-1].status == "failed"
    assert report.probes[-1].original_response_artifact == (
        "responses/python_patch_intent.json"
    )


def test_gate_accepts_an_applicable_behaviorally_equivalent_patch_intent(
    tmp_path: Path,
    valid_model_gate_responses: dict[str, dict[str, object]],
) -> None:
    responses = valid_model_gate_responses
    responses["python_patch_intent"]["edits"] = [
        {
            "old_text": "return configured or default",
            "new_text": "return default if configured is None else configured",
        }
    ]
    provider = FakeModelProvider(responses)

    report = model_gate.run_model_compatibility_gate(
        provider=provider,
        configuration=model_configuration(),
        output_directory=tmp_path / "gate",
    )

    assert report.compatible is True
    assert report.failure_category is None


def test_gate_accepts_canonical_hunk_with_omitted_single_line_count(
    tmp_path: Path,
    valid_model_gate_responses: dict[str, dict[str, object]],
) -> None:
    responses = valid_model_gate_responses
    responses["python_patch_intent"]["edits"] = [
        {
            "old_text": (
                "def select_timeout(configured: int | None, default: int) -> int:\n"
                "    return configured or default"
            ),
            "new_text": (
                "def select_timeout(configured: int | None, default: int) -> int: "
                "return configured if configured is not None else default"
            ),
        }
    ]

    report = model_gate.run_model_compatibility_gate(
        provider=FakeModelProvider(responses),
        configuration=model_configuration(),
        output_directory=tmp_path / "gate",
    )

    assert report.compatible is True
    assert report.failure_category is None


def test_gate_accepts_a_correct_patch_intent_with_sequential_control_flow(
    tmp_path: Path,
    valid_model_gate_responses: dict[str, dict[str, object]],
) -> None:
    responses = valid_model_gate_responses
    responses["python_patch_intent"]["edits"] = [
        {
            "old_text": "    return configured or default",
            "new_text": (
                "    if configured is None:\n"
                "        return default\n"
                "    return configured"
            ),
        }
    ]

    report = model_gate.run_model_compatibility_gate(
        provider=FakeModelProvider(responses),
        configuration=model_configuration(),
        output_directory=tmp_path / "gate",
    )

    assert report.compatible is True


def test_gate_rejects_an_applicable_patch_intent_that_breaks_required_behavior(
    tmp_path: Path,
    valid_model_gate_responses: dict[str, dict[str, object]],
) -> None:
    responses = valid_model_gate_responses
    responses["python_patch_intent"]["edits"] = [
        {"old_text": "return configured or default", "new_text": "return default"}
    ]

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
                persistence_safe_artifact=PersistenceSafeModelArtifact(
                    {"choices": [], "credential": "[REDACTED]"}
                ),
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
