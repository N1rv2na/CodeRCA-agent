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
) -> model_provider.OpenAICompatibleModelProvider:
    configuration, api_key = model_provider.load_model_environment(
        {
            "CODERCA_MODEL_BASE_URL": "https://models.example/v1",
            "CODERCA_MODEL_ID": "example-model",
            "CODERCA_MODEL_API_KEY": "secret-key",
        }
    )
    return model_provider.OpenAICompatibleModelProvider(
        configuration, api_key, transport=transport
    )


def test_model_configuration_is_loaded_from_the_three_canonical_variables() -> None:
    assert hasattr(model_provider, "ModelConfiguration")

    configuration, api_key = model_provider.load_model_environment(
        {
            "CODERCA_MODEL_BASE_URL": "https://models.example/v1/",
            "CODERCA_MODEL_ID": "example-model",
            "CODERCA_MODEL_API_KEY": "secret-key",
            "UNRELATED_MODEL_KEY": "ignored",
        }
    )

    assert configuration.base_url == "https://models.example/v1"
    assert configuration.chat_completions_url == (
        "https://models.example/v1/chat/completions"
    )
    assert configuration.model_id == "example-model"
    assert not hasattr(configuration, "api_key")
    assert api_key.get_secret_value() == "secret-key"


@pytest.mark.parametrize(
    "missing_name",
    [
        "CODERCA_MODEL_BASE_URL",
        "CODERCA_MODEL_ID",
        "CODERCA_MODEL_API_KEY",
    ],
)
def test_missing_model_configuration_has_an_actionable_error(
    missing_name: str,
) -> None:
    environment = {
        "CODERCA_MODEL_BASE_URL": "https://models.example/v1",
        "CODERCA_MODEL_ID": "example-model",
        "CODERCA_MODEL_API_KEY": "secret-key",
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
            ]
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
                        '{"stage": "hypothesis_generation", '
                        '"next_action": "inspect"}'
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

    assert response == model_provider.HttpResponse(
        status_code=200, body=b'{"ok":true}'
    )
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

    assert response.value == StageResult(
        stage="ready", next_action="inspect"
    )
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
        }
    )

    provider = model_provider.OpenAICompatibleModelProvider(
        configuration, api_key
    )

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
