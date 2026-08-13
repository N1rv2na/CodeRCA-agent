from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from coderca.model_provider import (
    GEMINI_BASE_URL,
    GEMINI_MODEL,
    GeminiErrorCategory,
    GeminiGateRequiredError,
    GeminiModelProvider,
    GeminiProviderError,
    TransportResponse,
)


def authorize_provider(
    provider: GeminiModelProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    from coderca.model_gate import GateResult, GeminiCompatibilityGate

    monkeypatch.setattr(
        GeminiCompatibilityGate,
        "run",
        lambda self, output_directory: GateResult(compatible=True),
    )
    provider.run_compatibility_gate(Path("unused-test-artifacts"))


@pytest.fixture(autouse=True)
def gemini_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "sentinel-key")


@dataclass
class RecordingTransport:
    response: TransportResponse

    def __post_init__(self) -> None:
        self.requests: list[Any] = []

    def request(self, request: Any) -> TransportResponse:
        self.requests.append(request)
        return self.response


def response(payload: dict[str, Any], status_code: int = 200) -> TransportResponse:
    return TransportResponse(status_code=status_code, body=json.dumps(payload))


def valid_payload() -> dict[str, Any]:
    return {
        "id": "chatcmpl-test",
        "model": GEMINI_MODEL,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": '{"ok": true}',
                    "extra_content": {"google": {"thought_signature": "opaque"}},
                },
                "finish_reason": "stop",
            }
        ],
    }


def test_provider_sends_fixed_gemini_request_without_key_in_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = RecordingTransport(response(valid_payload()))
    provider = GeminiModelProvider(transport=transport)
    authorize_provider(provider, monkeypatch)

    result = provider.complete_json("public probe prompt")

    request = transport.requests[0]
    assert request.url == f"{GEMINI_BASE_URL}chat/completions"
    assert request.json_body["model"] == GEMINI_MODEL
    assert request.json_body["temperature"] == 0
    assert request.json_body["response_format"] == {"type": "json_object"}
    assert "sentinel-key" not in json.dumps(request.json_body)
    assert result.content == {"ok": True}


def test_provider_preserves_thought_signature_and_round_trips_assistant_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = RecordingTransport(response(valid_payload()))
    provider = GeminiModelProvider(transport=transport)
    authorize_provider(provider, monkeypatch)

    first = provider.complete_json("first")
    provider.complete_json("continue", continuation=first)

    second_body = transport.requests[1].json_body
    assert first.provider_metadata == {
        "extra_content": {"google": {"thought_signature": "opaque"}}
    }
    assert first.assistant_message in second_body["messages"]


@pytest.mark.parametrize(
    ("status", "body", "category"),
    [
        (401, "unauthorized", GeminiErrorCategory.AUTHENTICATION),
        (403, "permission denied", GeminiErrorCategory.PERMISSION),
        (429, "quota exceeded", GeminiErrorCategory.QUOTA),
        (429, "rate limit exceeded", GeminiErrorCategory.RATE_LIMIT),
        (404, "model not found", GeminiErrorCategory.MODEL_UNAVAILABLE),
        (500, "server error", GeminiErrorCategory.NETWORK),
    ],
)
def test_provider_classifies_http_failures(
    status: int,
    body: str,
    category: GeminiErrorCategory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = RecordingTransport(TransportResponse(status_code=status, body=body))
    provider = GeminiModelProvider(transport=transport)
    authorize_provider(provider, monkeypatch)

    with pytest.raises(GeminiProviderError) as raised:
        provider.complete_json("public")

    assert raised.value.category is category
    assert "sentinel-key" not in str(raised.value)


def test_provider_rejects_missing_credentials_before_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    transport = RecordingTransport(response(valid_payload()))
    provider = GeminiModelProvider(transport=transport)

    with pytest.raises(GeminiProviderError) as raised:
        provider.preflight()

    assert raised.value.category is GeminiErrorCategory.MISSING_CREDENTIALS
    assert transport.requests == []


def test_provider_classifies_invalid_json_network_and_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for exception, category in [
        (ValueError("not json"), GeminiErrorCategory.INVALID_RESPONSE),
        (OSError("offline"), GeminiErrorCategory.NETWORK),
        (TimeoutError("slow"), GeminiErrorCategory.TIMEOUT),
    ]:
        class FailingTransport:
            def request(self, request: Any) -> TransportResponse:
                if isinstance(exception, ValueError):
                    return TransportResponse(status_code=200, body="not json")
                raise exception

        provider = GeminiModelProvider(transport=FailingTransport())
        authorize_provider(provider, monkeypatch)
        with pytest.raises(GeminiProviderError) as raised:
            provider.complete_json("public")
        assert raised.value.category is category


def test_provider_repr_does_not_include_key() -> None:
    provider = GeminiModelProvider(
        transport=RecordingTransport(response(valid_payload()))
    )
    assert "sentinel-key" not in repr(provider)


def test_provider_sends_explicit_json_schema_when_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = RecordingTransport(response(valid_payload()))
    provider = GeminiModelProvider(transport=transport)
    authorize_provider(provider, monkeypatch)
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}

    provider.complete_json("public", response_schema=schema)

    response_format = transport.requests[0].json_body["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True
    assert response_format["json_schema"]["schema"] == schema


def test_provider_blocks_diagnosis_completion_until_gate_passes(
    valid_manifest_data: dict[str, object],
) -> None:
    from coderca.contracts import TaskManifest

    transport = RecordingTransport(response(valid_payload()))
    provider = GeminiModelProvider(transport=transport)

    with pytest.raises(GeminiGateRequiredError):
        provider.complete(TaskManifest.model_validate(valid_manifest_data))

    assert transport.requests == []


def test_provider_blocks_public_structured_completion_until_gate_passes() -> None:
    transport = RecordingTransport(response(valid_payload()))
    provider = GeminiModelProvider(transport=transport)

    with pytest.raises(GeminiGateRequiredError):
        provider.complete_json("diagnosis stage request")

    assert transport.requests == []


def test_only_successful_provider_gate_authorizes_structured_completion(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from coderca.model_gate import GateResult, GeminiCompatibilityGate

    transport = RecordingTransport(response(valid_payload()))
    provider = GeminiModelProvider(transport=transport)
    monkeypatch.setattr(
        GeminiCompatibilityGate,
        "run",
        lambda self, output_directory: GateResult(compatible=True),
    )

    result = provider.run_compatibility_gate(tmp_path)
    completion = provider.complete_json("diagnosis stage request")

    assert result.compatible is True
    assert completion.content == {"ok": True}
