"""Model boundary used by the walking skeleton."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Generic, Literal, Mapping, Protocol, TypeVar
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from pydantic import BaseModel, SecretStr, ValidationError

from .contracts import ModelCompletion, TaskManifest

ModelFailureCategory = Literal[
    "configuration_error",
    "timeout",
    "network_error",
    "http_error",
    "invalid_json",
    "invalid_response",
    "schema_mismatch",
    "fake_response_missing",
    "model_mismatch",
    "patch_not_applicable",
]


class ModelProviderError(RuntimeError):
    """A provider-boundary failure safe to surface in structured reports."""

    def __init__(
        self,
        category: ModelFailureCategory,
        message: str,
        details: Mapping[str, object] | None = None,
        *,
        original_response: object | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.details = dict(details or {})
        self.original_response = original_response


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    body: bytes


class HttpTransport(Protocol):
    def post(
        self,
        url: str,
        headers: Mapping[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> HttpResponse:
        """Send one JSON HTTP POST request."""


class UrlLibHttpTransport:
    """Small standard-library transport with no provider-specific dependency."""

    def post(
        self,
        url: str,
        headers: Mapping[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> HttpResponse:
        request = Request(url, data=body, headers=dict(headers), method="POST")
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                return HttpResponse(status_code=response.status, body=response.read())
        except HTTPError as exc:
            return HttpResponse(status_code=exc.code, body=exc.read())


@dataclass(frozen=True)
class ModelConfiguration:
    """One operator-selected OpenAI-compatible endpoint and model."""

    base_url: str
    model_id: str

    @property
    def chat_completions_url(self) -> str:
        return f"{self.base_url}/chat/completions"


def load_model_environment(
    environment: Mapping[str, str] | None = None,
) -> tuple[ModelConfiguration, SecretStr]:
    values = os.environ if environment is None else environment
    names = (
        "CODERCA_MODEL_BASE_URL",
        "CODERCA_MODEL_ID",
        "CODERCA_MODEL_API_KEY",
    )
    missing = [name for name in names if not values.get(name, "").strip()]
    if missing:
        raise ModelProviderError(
            "configuration_error",
            "Model environment is missing required variables.",
            {"missing": missing},
        )
    base_url = values["CODERCA_MODEL_BASE_URL"].strip().rstrip("/")
    try:
        parsed_base_url = urlsplit(base_url)
        _ = parsed_base_url.port
    except ValueError as exc:
        raise ModelProviderError(
            "configuration_error",
            "CODERCA_MODEL_BASE_URL is not a valid HTTPS URL.",
            {"field": "CODERCA_MODEL_BASE_URL"},
        ) from exc
    if (
        parsed_base_url.scheme != "https"
        or not parsed_base_url.hostname
        or parsed_base_url.username is not None
        or parsed_base_url.password is not None
        or bool(parsed_base_url.query)
        or bool(parsed_base_url.fragment)
    ):
        raise ModelProviderError(
            "configuration_error",
            "CODERCA_MODEL_BASE_URL must be an HTTPS URL without credentials, "
            "query parameters, or a fragment.",
            {"field": "CODERCA_MODEL_BASE_URL"},
        )
    return (
        ModelConfiguration(
            base_url=base_url,
            model_id=values["CODERCA_MODEL_ID"].strip(),
        ),
        SecretStr(values["CODERCA_MODEL_API_KEY"].strip()),
    )


ResponseModel = TypeVar("ResponseModel", bound=BaseModel)


@dataclass(frozen=True)
class StructuredModelResponse(Generic[ResponseModel]):
    value: ResponseModel
    raw_response: object


class OpenAICompatibleModelProvider:
    """Strict structured-output adapter for one OpenAI-compatible endpoint."""

    def __init__(
        self,
        configuration: ModelConfiguration,
        api_key: SecretStr,
        *,
        transport: HttpTransport | None = None,
        timeout_seconds: float = 30,
    ) -> None:
        self.configuration = configuration
        self._api_key = api_key
        self.transport = transport if transport is not None else UrlLibHttpTransport()
        self.timeout_seconds = timeout_seconds

    def generate_structured(
        self,
        *,
        schema_name: str,
        system_prompt: str,
        user_prompt: str,
        response_model: type[ResponseModel],
    ) -> StructuredModelResponse[ResponseModel]:
        payload = {
            "model": self.configuration.model_id,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "temperature": 0,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": response_model.model_json_schema(),
                },
            },
        }
        try:
            response = self.transport.post(
                self.configuration.chat_completions_url,
                {
                    "Authorization": (
                        "Bearer "
                        f"{self._api_key.get_secret_value()}"
                    ),
                    "Content-Type": "application/json",
                },
                json.dumps(payload).encode("utf-8"),
                self.timeout_seconds,
            )
        except TimeoutError as exc:
            raise ModelProviderError(
                "timeout", "The model request exceeded its timeout."
            ) from exc
        except OSError as exc:
            raise ModelProviderError(
                "network_error", "The model endpoint could not be reached."
            ) from exc

        if not 200 <= response.status_code < 300:
            raise ModelProviderError(
                "http_error",
                "The model endpoint returned an unsuccessful HTTP status.",
                {"status_code": response.status_code},
                original_response=_response_body_artifact(
                    response.body, self._api_key.get_secret_value()
                ),
            )

        try:
            envelope = json.loads(response.body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ModelProviderError(
                "invalid_json",
                "The model endpoint returned invalid JSON.",
                original_response=_response_body_artifact(
                    response.body, self._api_key.get_secret_value()
                ),
            ) from exc

        sanitized_envelope = _redact_value(
            envelope, self._api_key.get_secret_value()
        )
        try:
            content = _extract_message_content(envelope)
        except ModelProviderError as exc:
            raise _error_with_original_response(exc, sanitized_envelope) from exc
        try:
            decoded_content = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ModelProviderError(
                "invalid_json",
                "The model message content was not valid JSON.",
                original_response=sanitized_envelope,
            ) from exc

        try:
            value = response_model.model_validate(decoded_content)
        except ValidationError as exc:
            error = _schema_mismatch_error(exc)
            raise _error_with_original_response(error, sanitized_envelope) from exc
        return StructuredModelResponse(
            value=value,
            raw_response=sanitized_envelope,
        )


def _extract_message_content(envelope: object) -> str:
    try:
        if not isinstance(envelope, dict):
            raise TypeError
        choices = envelope["choices"]
        if not isinstance(choices, list) or not choices:
            raise TypeError
        choice = choices[0]
        if not isinstance(choice, dict):
            raise TypeError
        message = choice["message"]
        if not isinstance(message, dict):
            raise TypeError
        content = message["content"]
        if not isinstance(content, str):
            raise TypeError
        return content
    except (KeyError, TypeError) as exc:
        raise ModelProviderError(
            "invalid_response",
            "The model endpoint returned an invalid Chat Completions envelope.",
        ) from exc


class ModelProvider(Protocol):
    def complete(self, manifest: TaskManifest) -> ModelCompletion:
        """Return a structured completion for a manifest."""


class FakeModelProvider:
    """Deterministic, no-I/O provider for local development and tests."""

    def __init__(
        self, structured_responses: Mapping[str, object] | None = None
    ) -> None:
        self.structured_responses = dict(structured_responses or {})
        self.structured_calls: list[str] = []

    def complete(self, manifest: TaskManifest) -> ModelCompletion:
        return ModelCompletion(
            summary=(
                "Fake model completed the walking-skeleton diagnosis for "
                f"task {manifest.task_id}; no root-cause candidates were produced."
            )
        )

    def generate_structured(
        self,
        *,
        schema_name: str,
        system_prompt: str,
        user_prompt: str,
        response_model: type[ResponseModel],
    ) -> StructuredModelResponse[ResponseModel]:
        self.structured_calls.append(schema_name)
        if schema_name not in self.structured_responses:
            raise ModelProviderError(
                "fake_response_missing",
                f"No structured fake response is registered for {schema_name}.",
            )
        try:
            value = response_model.model_validate(
                self.structured_responses[schema_name]
            )
        except ValidationError as exc:
            error = _schema_mismatch_error(exc)
            raise _error_with_original_response(
                error, self.structured_responses[schema_name]
            ) from exc
        return StructuredModelResponse(
            value=value,
            raw_response=self.structured_responses[schema_name],
        )


def _schema_mismatch_error(error: ValidationError) -> ModelProviderError:
    errors = [
        {"type": item["type"], "loc": list(item["loc"])}
        for item in error.errors()
    ]
    return ModelProviderError(
        "schema_mismatch",
        "The model message did not satisfy the requested schema.",
        {"validation_errors": errors},
    )


def _error_with_original_response(
    error: ModelProviderError, original_response: object
) -> ModelProviderError:
    return ModelProviderError(
        error.category,
        str(error),
        error.details,
        original_response=original_response,
    )


def _response_body_artifact(body: bytes, secret: str) -> object:
    try:
        decoded = body.decode("utf-8")
    except UnicodeDecodeError:
        return "[NON_UTF8_RESPONSE_BODY]"
    try:
        value = json.loads(decoded)
    except json.JSONDecodeError:
        value = decoded
    return _redact_value(value, secret)


def _redact_value(value: object, secret: str) -> object:
    if isinstance(value, str):
        return value.replace(secret, "[REDACTED]")
    if isinstance(value, list):
        return [_redact_value(item, secret) for item in value]
    if isinstance(value, dict):
        return {
            str(key).replace(secret, "[REDACTED]"): _redact_value(item, secret)
            for key, item in value.items()
        }
    return value
