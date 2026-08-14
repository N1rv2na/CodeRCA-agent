from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socket import SHUT_RDWR
from threading import Thread
from time import sleep
from typing import Any, Iterator, Mapping
from urllib.request import ProxyHandler, Request, build_opener

import pytest
from pydantic import BaseModel, ConfigDict, SecretStr

from coderca import model_provider


class StageResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: str
    next_action: str


@dataclass
class RecordedRequest:
    url: str
    headers: Mapping[str, str]
    body: bytes
    timeout_seconds: float


class StubTransport:
    def __init__(self, response: object) -> None:
        self.response = response
        self.requests: list[RecordedRequest] = []

    def post(
        self,
        url: str,
        headers: Mapping[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> model_provider.HttpResponse:
        self.requests.append(RecordedRequest(url, headers, body, timeout_seconds))
        return model_provider.HttpResponse(
            status_code=200,
            body=json.dumps(self.response).encode(),
        )


class RaisingTransport:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def post(
        self,
        url: str,
        headers: Mapping[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> model_provider.HttpResponse:
        raise self.error


@pytest.fixture
def direct_loopback_urlopen(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep loopback integration tests independent from host proxy settings."""

    opener = build_opener(ProxyHandler({}))
    monkeypatch.setattr(model_provider, "urlopen", opener.open)


@contextmanager
def running_loopback_server(
    handler: type[BaseHTTPRequestHandler],
) -> Iterator[ThreadingHTTPServer]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def make_provider(
    transport: model_provider.HttpTransport,
    mode: str = "native_json_schema",
    request_extensions: str | None = None,
    base_url: str = "https://models.example/v1",
    model_id: str = "example-model",
) -> model_provider.OpenAICompatibleModelProvider:
    environment = {
        "CODERCA_MODEL_BASE_URL": base_url,
        "CODERCA_MODEL_ID": model_id,
        "CODERCA_MODEL_API_KEY": "secret-key",
        "CODERCA_MODEL_STRUCTURED_OUTPUT_MODE": mode,
    }
    if request_extensions is not None:
        environment["CODERCA_MODEL_REQUEST_EXTENSIONS"] = request_extensions
    configuration, api_key = model_provider.load_model_environment(environment)
    return model_provider.OpenAICompatibleModelProvider(
        configuration, api_key, transport=transport
    )


def test_model_configuration_defaults_request_extensions_to_empty() -> None:
    assert hasattr(model_provider, "ModelConfiguration")

    configuration, api_key = model_provider.load_model_environment(
        {
            "CODERCA_MODEL_BASE_URL": "https://models.example/v1/",
            "CODERCA_MODEL_ID": "example-model",
            "CODERCA_MODEL_API_KEY": "secret-key",
            "CODERCA_MODEL_STRUCTURED_OUTPUT_MODE": "json_text",
            "UNRELATED_MODEL_KEY": "ignored",
        }
    )

    assert configuration.base_url == "https://models.example/v1"
    assert configuration.chat_completions_url == (
        "https://models.example/v1/chat/completions"
    )
    assert configuration.model_id == "example-model"
    assert configuration.structured_output_mode.value == "json_text"
    assert dict(configuration.request_extensions) == {}
    assert not hasattr(configuration, "api_key")
    assert api_key.get_secret_value() == "secret-key"


def test_blank_request_extensions_environment_value_defaults_to_empty() -> None:
    configuration, _ = model_provider.load_model_environment(
        {
            "CODERCA_MODEL_BASE_URL": "https://models.example/v1",
            "CODERCA_MODEL_ID": "example-model",
            "CODERCA_MODEL_API_KEY": "secret-key",
            "CODERCA_MODEL_STRUCTURED_OUTPUT_MODE": "json_text",
            "CODERCA_MODEL_REQUEST_EXTENSIONS": "   ",
        }
    )

    assert dict(configuration.request_extensions) == {}


def test_model_configuration_loads_explicit_json_request_extensions() -> None:
    configuration, _ = model_provider.load_model_environment(
        {
            "CODERCA_MODEL_BASE_URL": "https://models.example/v1",
            "CODERCA_MODEL_ID": "example-model",
            "CODERCA_MODEL_API_KEY": "secret-key",
            "CODERCA_MODEL_STRUCTURED_OUTPUT_MODE": "json_text",
            "CODERCA_MODEL_REQUEST_EXTENSIONS": (
                '{"reasoning_split":true,"thinking":{"type":"adaptive"}}'
            ),
        }
    )

    assert dict(configuration.request_extensions) == {
        "reasoning_split": True,
        "thinking": {"type": "adaptive"},
    }


@pytest.mark.parametrize(
    ("raw_extensions", "reason"),
    [
        ("{not-json", "invalid_json"),
        ("[]", "not_object"),
        ('"reasoning_split"', "not_object"),
    ],
)
def test_model_configuration_rejects_invalid_request_extensions(
    raw_extensions: str, reason: str
) -> None:
    with pytest.raises(model_provider.ModelProviderError) as raised:
        model_provider.load_model_environment(
            {
                "CODERCA_MODEL_BASE_URL": "https://models.example/v1",
                "CODERCA_MODEL_ID": "example-model",
                "CODERCA_MODEL_API_KEY": "secret-key",
                "CODERCA_MODEL_STRUCTURED_OUTPUT_MODE": "json_text",
                "CODERCA_MODEL_REQUEST_EXTENSIONS": raw_extensions,
            }
        )

    assert raised.value.category == "configuration_error"
    assert raised.value.details == {
        "field": "CODERCA_MODEL_REQUEST_EXTENSIONS",
        "reason": reason,
    }


@pytest.mark.parametrize(
    "protected_key",
    ["model", "messages", "stream", "temperature", "response_format"],
)
def test_model_configuration_rejects_protected_request_extension_keys(
    protected_key: str,
) -> None:
    with pytest.raises(model_provider.ModelProviderError) as raised:
        model_provider.load_model_environment(
            {
                "CODERCA_MODEL_BASE_URL": "https://models.example/v1",
                "CODERCA_MODEL_ID": "example-model",
                "CODERCA_MODEL_API_KEY": "secret-key",
                "CODERCA_MODEL_STRUCTURED_OUTPUT_MODE": "json_text",
                "CODERCA_MODEL_REQUEST_EXTENSIONS": json.dumps({protected_key: True}),
            }
        )

    assert raised.value.category == "configuration_error"
    assert raised.value.details == {
        "field": "CODERCA_MODEL_REQUEST_EXTENSIONS",
        "protected_keys": [protected_key],
    }


@pytest.mark.parametrize(
    "missing_name",
    [
        "CODERCA_MODEL_BASE_URL",
        "CODERCA_MODEL_ID",
        "CODERCA_MODEL_API_KEY",
        "CODERCA_MODEL_STRUCTURED_OUTPUT_MODE",
    ],
)
def test_missing_model_configuration_has_an_actionable_error(
    missing_name: str,
) -> None:
    environment = {
        "CODERCA_MODEL_BASE_URL": "https://models.example/v1",
        "CODERCA_MODEL_ID": "example-model",
        "CODERCA_MODEL_API_KEY": "secret-key",
        "CODERCA_MODEL_STRUCTURED_OUTPUT_MODE": "native_json_schema",
    }
    del environment[missing_name]

    with pytest.raises(model_provider.ModelProviderError) as raised:
        model_provider.load_model_environment(environment)

    assert raised.value.category == "configuration_error"
    assert raised.value.details == {"missing": [missing_name]}
    assert "secret-key" not in str(raised.value)


def test_provider_sends_strict_chat_completion_and_validates_the_response() -> None:
    configuration, api_key = model_provider.load_model_environment(
        {
            "CODERCA_MODEL_BASE_URL": "https://models.example/v1/",
            "CODERCA_MODEL_ID": "example-model",
            "CODERCA_MODEL_API_KEY": "secret-key",
            "CODERCA_MODEL_STRUCTURED_OUTPUT_MODE": "native_json_schema",
        }
    )
    transport = StubTransport(
        {
            "provider_metadata": {"echoed_credential": "secret-key"},
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {"stage": "hypothesis_generation", "next_action": "inspect"}
                        )
                    }
                }
            ],
        }
    )
    provider = model_provider.OpenAICompatibleModelProvider(
        configuration, api_key, transport=transport, timeout_seconds=12
    )

    result = provider.generate_structured(
        schema_name="stage_probe",
        system_prompt="Return the requested decision.",
        user_prompt="A CI test failed.",
        response_model=StageResult,
    )

    assert result.value == StageResult(
        stage="hypothesis_generation", next_action="inspect"
    )
    assert result.raw_response == {
        "provider_metadata": {"echoed_credential": "[REDACTED]"},
        "choices": [
            {
                "message": {
                    "content": (
                        '{"stage": "hypothesis_generation", "next_action": "inspect"}'
                    )
                }
            }
        ],
    }
    assert len(transport.requests) == 1
    request = transport.requests[0]
    assert request.url == "https://models.example/v1/chat/completions"
    assert request.headers == {
        "Authorization": "Bearer secret-key",
        "Content-Type": "application/json",
    }
    assert request.timeout_seconds == 12
    payload = json.loads(request.body)
    assert set(payload) == {
        "model",
        "messages",
        "stream",
        "temperature",
        "response_format",
    }
    assert payload["model"] == "example-model"
    assert payload["stream"] is False
    assert payload["temperature"] == 0
    assert payload["messages"] == [
        {"role": "system", "content": "Return the requested decision."},
        {"role": "user", "content": "A CI test failed."},
    ]
    assert payload["response_format"]["type"] == "json_schema"
    schema = payload["response_format"]["json_schema"]
    assert schema["name"] == "stage_probe"
    assert schema["strict"] is True
    assert schema["schema"] == StageResult.model_json_schema()


def test_json_text_mode_omits_response_format_and_validates_raw_json() -> None:
    transport = StubTransport(
        {
            "provider_metadata": {"echoed_credential": "secret-key"},
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"stage":"hypothesis_generation","next_action":"inspect"}'
                        )
                    }
                }
            ],
        }
    )
    provider = make_provider(transport, mode="json_text")

    result = provider.generate_structured(
        schema_name="stage_probe",
        system_prompt="Return the requested decision.",
        user_prompt="A CI test failed.",
        response_model=StageResult,
    )

    assert result.value == StageResult(
        stage="hypothesis_generation", next_action="inspect"
    )
    assert "secret-key" not in json.dumps(result.raw_response)
    payload = json.loads(transport.requests[0].body)
    assert "response_format" not in payload
    system_content = payload["messages"][0]["content"]
    assert "Return exactly one raw JSON value" in system_content
    assert "Do not use Markdown fences" in system_content
    assert '"additionalProperties": false' in system_content


def test_json_text_mode_adds_request_extensions_without_provider_inference() -> None:
    transport = StubTransport(
        {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"stage":"hypothesis_generation","next_action":"inspect"}'
                        )
                    }
                }
            ]
        }
    )
    provider = make_provider(
        transport,
        mode="json_text",
        request_extensions='{"reasoning_split":true}',
    )

    provider.generate_structured(
        schema_name="stage_probe",
        system_prompt="Return the requested decision.",
        user_prompt="A CI test failed.",
        response_model=StageResult,
    )

    payload = json.loads(transport.requests[0].body)
    assert payload["reasoning_split"] is True
    assert "response_format" not in payload
    assert payload["model"] == "example-model"


@pytest.mark.parametrize(
    ("base_url", "model_id"),
    [
        ("https://api.minimax.example/v1", "MiniMax-M3"),
        ("https://modelscope.example/v1", "GLM-5.2"),
    ],
)
def test_request_extensions_do_not_trigger_endpoint_or_model_name_branches(
    base_url: str, model_id: str
) -> None:
    transport = StubTransport(
        {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"stage":"hypothesis_generation","next_action":"inspect"}'
                        )
                    }
                }
            ]
        }
    )
    provider = make_provider(
        transport,
        mode="json_text",
        request_extensions='{"explicit_extension":true}',
        base_url=base_url,
        model_id=model_id,
    )

    provider.generate_structured(
        schema_name="stage_probe",
        system_prompt="Return the requested decision.",
        user_prompt="A CI test failed.",
        response_model=StageResult,
    )

    payload = json.loads(transport.requests[0].body)
    assert set(payload) == {
        "model",
        "messages",
        "stream",
        "temperature",
        "explicit_extension",
    }
    assert payload["model"] == model_id
    assert payload["explicit_extension"] is True


def test_provider_redacts_echoed_string_request_extension_values() -> None:
    transport = StubTransport(
        {
            "provider_metadata": {"echoed_extension": "private-extension-value"},
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"stage":"hypothesis_generation","next_action":"inspect"}'
                        )
                    }
                }
            ],
        }
    )
    provider = make_provider(
        transport,
        mode="json_text",
        request_extensions=(
            '{"endpoint_option":{"private_value":"private-extension-value"}}'
        ),
    )

    response = provider.generate_structured(
        schema_name="stage_probe",
        system_prompt="Return the requested decision.",
        user_prompt="A CI test failed.",
        response_model=StageResult,
    )

    serialized = json.dumps(response.raw_response)
    assert "private-extension-value" not in serialized
    assert "[REDACTED]" in serialized


@pytest.mark.parametrize(
    "content",
    [
        '```json\n{"stage":"hypothesis_generation","next_action":"inspect"}\n```',
        (
            "<think>reasoning</think>"
            '{"stage":"hypothesis_generation","next_action":"inspect"}'
        ),
        (
            "Here is the result: "
            '{"stage":"hypothesis_generation","next_action":"inspect"}'
        ),
    ],
)
def test_json_text_mode_rejects_wrapped_json_without_fuzzy_extraction(
    content: str,
) -> None:
    transport = StubTransport({"choices": [{"message": {"content": content}}]})
    provider = make_provider(transport, mode="json_text")

    with pytest.raises(model_provider.ModelProviderError) as raised:
        provider.generate_structured(
            schema_name="stage_probe",
            system_prompt="system",
            user_prompt="user",
            response_model=StageResult,
        )

    assert raised.value.category == "invalid_json"
    assert len(transport.requests) == 1


@pytest.mark.parametrize(
    "mode",
    ["native_json_schema", "json_text"],
)
def test_all_structured_output_modes_reject_locally_invalid_schema(
    mode: str,
) -> None:
    transport = StubTransport(
        {"choices": [{"message": {"content": '{"stage":"ready"}'}}]}
    )
    provider = make_provider(transport, mode=mode)

    with pytest.raises(model_provider.ModelProviderError) as raised:
        provider.generate_structured(
            schema_name="stage_probe",
            system_prompt="system",
            user_prompt="user",
            response_model=StageResult,
        )

    assert raised.value.category == "schema_mismatch"
    assert len(transport.requests) == 1


def test_model_configuration_rejects_unknown_structured_output_mode() -> None:
    with pytest.raises(model_provider.ModelProviderError) as raised:
        model_provider.load_model_environment(
            {
                "CODERCA_MODEL_BASE_URL": "https://models.example/v1",
                "CODERCA_MODEL_ID": "example-model",
                "CODERCA_MODEL_API_KEY": "secret-key",
                "CODERCA_MODEL_STRUCTURED_OUTPUT_MODE": "auto",
            }
        )

    assert raised.value.category == "configuration_error"
    assert raised.value.details == {
        "field": "CODERCA_MODEL_STRUCTURED_OUTPUT_MODE",
        "allowed": ["native_json_schema", "json_text"],
    }


@pytest.mark.parametrize(
    ("transport", "expected_category"),
    [
        (RaisingTransport(TimeoutError("secret-key timed out")), "timeout"),
        (RaisingTransport(OSError("secret-key network down")), "network_error"),
        (
            StubTransport("not an object"),
            "invalid_response",
        ),
    ],
)
def test_provider_normalizes_transport_and_envelope_failures(
    transport: model_provider.HttpTransport, expected_category: str
) -> None:
    provider = make_provider(transport)

    with pytest.raises(model_provider.ModelProviderError) as raised:
        provider.generate_structured(
            schema_name="stage_probe",
            system_prompt="system",
            user_prompt="user",
            response_model=StageResult,
        )

    assert raised.value.category == expected_category
    assert "secret-key" not in str(raised.value)
    assert "secret-key" not in json.dumps(raised.value.details)
    if expected_category == "invalid_response":
        assert raised.value.original_response is not None
        assert "secret-key" not in json.dumps(raised.value.original_response)
    else:
        assert raised.value.original_response is None


@pytest.mark.parametrize(
    ("response", "expected_category"),
    [
        (
            model_provider.HttpResponse(
                status_code=429, body=b'{"error":{"message":"secret-key quota"}}'
            ),
            "http_error",
        ),
        (
            model_provider.HttpResponse(status_code=200, body=b"not-json"),
            "invalid_json",
        ),
        (
            model_provider.HttpResponse(status_code=200, body=b'{"choices":[]}'),
            "invalid_response",
        ),
        (
            model_provider.HttpResponse(
                status_code=200,
                body=json.dumps(
                    {"choices": [{"message": {"content": "not-json"}}]}
                ).encode(),
            ),
            "invalid_json",
        ),
        (
            model_provider.HttpResponse(
                status_code=200,
                body=json.dumps(
                    {"choices": [{"message": {"content": '{"stage":"x"}'}}]}
                ).encode(),
            ),
            "schema_mismatch",
        ),
    ],
)
def test_provider_classifies_http_json_and_schema_failures(
    response: model_provider.HttpResponse, expected_category: str
) -> None:
    class FixedResponseTransport:
        def post(
            self,
            url: str,
            headers: Mapping[str, str],
            body: bytes,
            timeout_seconds: float,
        ) -> model_provider.HttpResponse:
            return response

    provider = make_provider(FixedResponseTransport())

    with pytest.raises(model_provider.ModelProviderError) as raised:
        provider.generate_structured(
            schema_name="stage_probe",
            system_prompt="system",
            user_prompt="user",
            response_model=StageResult,
        )

    assert raised.value.category == expected_category
    assert "secret-key" not in str(raised.value)
    assert "secret-key" not in json.dumps(raised.value.details)
    assert raised.value.original_response is not None
    assert "secret-key" not in json.dumps(raised.value.original_response)


def test_default_transport_posts_the_request_with_urllib(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakeUrlResponse:
        status = 200

        def __enter__(self) -> FakeUrlResponse:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"ok":true}'

    def fake_urlopen(request: Request, timeout: float) -> FakeUrlResponse:
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeUrlResponse()

    monkeypatch.setattr(model_provider, "urlopen", fake_urlopen, raising=False)
    transport = model_provider.UrlLibHttpTransport()

    response = transport.post(
        "https://models.example/v1/chat/completions",
        {"Authorization": "Bearer secret-key", "Content-Type": "application/json"},
        b'{"model":"example-model"}',
        12,
    )

    assert response == model_provider.HttpResponse(status_code=200, body=b'{"ok":true}')
    request = captured["request"]
    assert isinstance(request, Request)
    assert request.full_url == "https://models.example/v1/chat/completions"
    assert request.get_header("Authorization") == "Bearer secret-key"
    assert request.get_header("Content-type") == "application/json"
    assert request.data == b'{"model":"example-model"}'
    assert captured["timeout"] == 12


def test_provider_integrates_with_a_local_fake_http_service(
    direct_loopback_urlopen: None,
) -> None:
    captured: dict[str, object] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers["Content-Length"])
            captured["path"] = self.path
            captured["authorization"] = self.headers["Authorization"]
            captured["body"] = self.rfile.read(length)
            response = json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {"stage": "ready", "next_action": "inspect"}
                                )
                            }
                        }
                    ]
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        def log_message(self, format: str, *args: object) -> None:
            return None

    with running_loopback_server(Handler) as server:
        provider = model_provider.OpenAICompatibleModelProvider(
            model_provider.ModelConfiguration(
                base_url=f"http://127.0.0.1:{server.server_port}/v1",
                model_id="fake-model",
                structured_output_mode=(
                    model_provider.StructuredOutputMode.NATIVE_JSON_SCHEMA
                ),
            ),
            SecretStr("fake-key"),
            timeout_seconds=2,
        )
        response = provider.generate_structured(
            schema_name="stage_probe",
            system_prompt="Return a stage.",
            user_prompt="Inspect the failure.",
            response_model=StageResult,
        )

    assert response.value == StageResult(stage="ready", next_action="inspect")
    assert captured["path"] == "/v1/chat/completions"
    assert captured["authorization"] == "Bearer fake-key"
    request_body = captured["body"]
    assert isinstance(request_body, bytes)
    request_payload = json.loads(request_body)
    assert request_payload["model"] == "fake-model"
    assert request_payload["response_format"]["type"] == "json_schema"


@pytest.mark.parametrize(
    ("status_code", "response_body", "expected_category"),
    [
        (429, b'{"error":{"message":"fake-key quota"}}', "http_error"),
        (200, b"not-json", "invalid_json"),
        (200, b'{"choices":[]}', "invalid_response"),
        (
            200,
            b'{"choices":[{"message":{"content":"{\\"stage\\":\\"ready\\"}"}}]}',
            "schema_mismatch",
        ),
    ],
)
def test_provider_classifies_fake_http_service_failures(
    status_code: int,
    response_body: bytes,
    expected_category: str,
    direct_loopback_urlopen: None,
) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response_body)))
            self.end_headers()
            self.wfile.write(response_body)

        def log_message(self, format: str, *args: object) -> None:
            return None

    with running_loopback_server(Handler) as server:
        provider = model_provider.OpenAICompatibleModelProvider(
            model_provider.ModelConfiguration(
                base_url=f"http://127.0.0.1:{server.server_port}/v1",
                model_id="fake-model",
                structured_output_mode=(
                    model_provider.StructuredOutputMode.NATIVE_JSON_SCHEMA
                ),
            ),
            SecretStr("fake-key"),
            timeout_seconds=2,
        )
        with pytest.raises(model_provider.ModelProviderError) as raised:
            provider.generate_structured(
                schema_name="stage_probe",
                system_prompt="Return a stage.",
                user_prompt="Inspect the failure.",
                response_model=StageResult,
            )

    assert raised.value.category == expected_category
    assert raised.value.original_response is not None
    assert "fake-key" not in json.dumps(raised.value.original_response)


def test_provider_classifies_fake_http_timeout(
    direct_loopback_urlopen: None,
) -> None:
    class SlowHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            sleep(0.05)
            try:
                self.send_response(200)
                self.end_headers()
            except BrokenPipeError:
                pass

        def log_message(self, format: str, *args: object) -> None:
            return None

    with running_loopback_server(SlowHandler) as server:
        provider = model_provider.OpenAICompatibleModelProvider(
            model_provider.ModelConfiguration(
                base_url=f"http://127.0.0.1:{server.server_port}/v1",
                model_id="fake-model",
                structured_output_mode=(
                    model_provider.StructuredOutputMode.NATIVE_JSON_SCHEMA
                ),
            ),
            SecretStr("fake-key"),
            timeout_seconds=0.001,
        )
        with pytest.raises(model_provider.ModelProviderError) as raised:
            provider.generate_structured(
                schema_name="stage_probe",
                system_prompt="Return a stage.",
                user_prompt="Inspect the failure.",
                response_model=StageResult,
            )

    assert raised.value.category == "timeout"
    assert raised.value.original_response is None


def test_provider_classifies_fake_http_connection_drop(
    direct_loopback_urlopen: None,
) -> None:
    class DisconnectingHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            self.connection.shutdown(SHUT_RDWR)
            self.connection.close()

        def log_message(self, format: str, *args: object) -> None:
            return None

    with running_loopback_server(DisconnectingHandler) as server:
        provider = model_provider.OpenAICompatibleModelProvider(
            model_provider.ModelConfiguration(
                base_url=f"http://127.0.0.1:{server.server_port}/v1",
                model_id="fake-model",
                structured_output_mode=(
                    model_provider.StructuredOutputMode.NATIVE_JSON_SCHEMA
                ),
            ),
            SecretStr("fake-key"),
            timeout_seconds=2,
        )
        with pytest.raises(model_provider.ModelProviderError) as raised:
            provider.generate_structured(
                schema_name="stage_probe",
                system_prompt="Return a stage.",
                user_prompt="Inspect the failure.",
                response_model=StageResult,
            )

    assert raised.value.category == "network_error"
    assert raised.value.original_response is None


def test_provider_uses_the_standard_library_transport_by_default() -> None:
    configuration, api_key = model_provider.load_model_environment(
        {
            "CODERCA_MODEL_BASE_URL": "https://models.example/v1",
            "CODERCA_MODEL_ID": "example-model",
            "CODERCA_MODEL_API_KEY": "secret-key",
            "CODERCA_MODEL_STRUCTURED_OUTPUT_MODE": "native_json_schema",
        }
    )

    provider = model_provider.OpenAICompatibleModelProvider(configuration, api_key)

    assert isinstance(provider.transport, model_provider.UrlLibHttpTransport)


@pytest.mark.parametrize(
    "base_url",
    [
        "http://models.example/v1",
        "https://user:password@models.example/v1",
        "https://models.example/v1?api_key=secret-key",
        "https://models.example/v1#fragment",
        "models.example/v1",
    ],
)
def test_model_configuration_rejects_unsafe_or_invalid_base_urls(
    base_url: str,
) -> None:
    with pytest.raises(model_provider.ModelProviderError) as raised:
        model_provider.load_model_environment(
            {
                "CODERCA_MODEL_BASE_URL": base_url,
                "CODERCA_MODEL_ID": "example-model",
                "CODERCA_MODEL_API_KEY": "secret-key",
                "CODERCA_MODEL_STRUCTURED_OUTPUT_MODE": "native_json_schema",
            }
        )

    assert raised.value.category == "configuration_error"
    assert raised.value.details == {"field": "CODERCA_MODEL_BASE_URL"}
    assert "secret-key" not in str(raised.value)
    assert "secret-key" not in json.dumps(raised.value.details)


def test_fake_model_provider_implements_the_structured_provider_contract() -> None:
    provider = model_provider.FakeModelProvider(
        structured_responses={
            "stage_probe": {
                "stage": "hypothesis_generation",
                "next_action": "inspect",
            }
        }
    )

    result = provider.generate_structured(
        schema_name="stage_probe",
        system_prompt="system",
        user_prompt="user",
        response_model=StageResult,
    )

    assert result.value == StageResult(
        stage="hypothesis_generation", next_action="inspect"
    )
    assert provider.structured_calls == ["stage_probe"]
