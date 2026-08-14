"""Model boundary used by the walking skeleton."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Generic, Literal, Mapping, Protocol, TypeVar
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from pydantic import BaseModel, JsonValue, SecretStr, ValidationError

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


class StructuredOutputMode(str, Enum):
    """Explicit request strategy for locally validated model output."""

    NATIVE_JSON_SCHEMA = "native_json_schema"
    JSON_TEXT = "json_text"


_PROTECTED_REQUEST_KEYS = frozenset(
    {"model", "messages", "stream", "temperature", "response_format"}
)


@dataclass(frozen=True)
class ModelConfiguration:
    """One operator-selected endpoint, model, and structured-output mode."""

    base_url: str
    model_id: str
    structured_output_mode: StructuredOutputMode
    request_extensions: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        request_extensions = deepcopy(dict(self.request_extensions))
        protected_keys = sorted(
            _PROTECTED_REQUEST_KEYS.intersection(request_extensions)
        )
        if protected_keys:
            raise ModelProviderError(
                "configuration_error",
                "Model request extensions cannot override protected fields.",
                {
                    "field": "CODERCA_MODEL_REQUEST_EXTENSIONS",
                    "protected_keys": protected_keys,
                },
            )
        try:
            json.dumps(request_extensions, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ModelProviderError(
                "configuration_error",
                "Model request extensions must contain only JSON values.",
                {
                    "field": "CODERCA_MODEL_REQUEST_EXTENSIONS",
                    "reason": "invalid_json_value",
                },
            ) from exc
        object.__setattr__(
            self,
            "request_extensions",
            MappingProxyType(request_extensions),
        )

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
        "CODERCA_MODEL_STRUCTURED_OUTPUT_MODE",
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
    raw_mode = values["CODERCA_MODEL_STRUCTURED_OUTPUT_MODE"].strip()
    try:
        structured_output_mode = StructuredOutputMode(raw_mode)
    except ValueError as exc:
        raise ModelProviderError(
            "configuration_error",
            "CODERCA_MODEL_STRUCTURED_OUTPUT_MODE is not supported.",
            {
                "field": "CODERCA_MODEL_STRUCTURED_OUTPUT_MODE",
                "allowed": [mode.value for mode in StructuredOutputMode],
            },
        ) from exc
    raw_request_extensions = values.get("CODERCA_MODEL_REQUEST_EXTENSIONS", "").strip()
    request_extensions: dict[str, JsonValue] = {}
    if raw_request_extensions:
        try:
            decoded_extensions = json.loads(raw_request_extensions)
        except json.JSONDecodeError as exc:
            raise ModelProviderError(
                "configuration_error",
                "CODERCA_MODEL_REQUEST_EXTENSIONS must be valid JSON.",
                {
                    "field": "CODERCA_MODEL_REQUEST_EXTENSIONS",
                    "reason": "invalid_json",
                },
            ) from exc
        if not isinstance(decoded_extensions, dict):
            raise ModelProviderError(
                "configuration_error",
                "CODERCA_MODEL_REQUEST_EXTENSIONS must be a JSON object.",
                {
                    "field": "CODERCA_MODEL_REQUEST_EXTENSIONS",
                    "reason": "not_object",
                },
            )
        request_extensions = decoded_extensions
    return (
        ModelConfiguration(
            base_url=base_url,
            model_id=values["CODERCA_MODEL_ID"].strip(),
            structured_output_mode=structured_output_mode,
            request_extensions=request_extensions,
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
        redaction_values = _request_redaction_values(
            self._api_key.get_secret_value(),
            self.configuration.request_extensions,
        )
        system_content = system_prompt
        if self.configuration.structured_output_mode is StructuredOutputMode.JSON_TEXT:
            schema = json.dumps(response_model.model_json_schema(), sort_keys=True)
            system_content = (
                f"{system_prompt}\n"
                "Return exactly one raw JSON value matching this JSON Schema: "
                f"{schema}\n"
                "Do not use Markdown fences, reasoning tags, commentary, or "
                "text before or after the JSON value."
            )
        payload: dict[str, object] = {
            "model": self.configuration.model_id,
            "messages": [
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "temperature": 0,
        }
        if (
            self.configuration.structured_output_mode
            is StructuredOutputMode.NATIVE_JSON_SCHEMA
        ):
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": response_model.model_json_schema(),
                },
            }
        for key, extension_value in self.configuration.request_extensions.items():
            if key in payload:
                raise ModelProviderError(
                    "configuration_error",
                    "Model request extensions cannot override provider fields.",
                    {
                        "field": "CODERCA_MODEL_REQUEST_EXTENSIONS",
                        "protected_keys": [key],
                    },
                )
            payload[key] = extension_value
        try:
            response = self.transport.post(
                self.configuration.chat_completions_url,
                {
                    "Authorization": (f"Bearer {self._api_key.get_secret_value()}"),
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
                    response.body, redaction_values
                ),
            )

        try:
            envelope = json.loads(response.body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ModelProviderError(
                "invalid_json",
                "The model endpoint returned invalid JSON.",
                original_response=_response_body_artifact(
                    response.body, redaction_values
                ),
            ) from exc

        sanitized_envelope = _redact_value(envelope, redaction_values)
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
        {"type": item["type"], "loc": list(item["loc"])} for item in error.errors()
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


def _request_redaction_values(
    api_key: str, request_extensions: Mapping[str, JsonValue]
) -> tuple[str, ...]:
    values = {api_key}
    pending: list[JsonValue] = list(request_extensions.values())
    while pending:
        value = pending.pop()
        if isinstance(value, str):
            if value:
                values.add(value)
        elif isinstance(value, list):
            pending.extend(value)
        elif isinstance(value, dict):
            pending.extend(value.values())
    return tuple(sorted(values, key=len, reverse=True))


def _response_body_artifact(body: bytes, redaction_values: tuple[str, ...]) -> object:
    try:
        decoded = body.decode("utf-8")
    except UnicodeDecodeError:
        return "[NON_UTF8_RESPONSE_BODY]"
    try:
        value = json.loads(decoded)
    except json.JSONDecodeError:
        value = decoded
    return _redact_value(value, redaction_values)


def _redact_value(value: object, redaction_values: tuple[str, ...]) -> object:
    if isinstance(value, str):
        redacted = value
        for redaction_value in redaction_values:
            redacted = redacted.replace(redaction_value, "[REDACTED]")
        return redacted
    if isinstance(value, list):
        return [_redact_value(item, redaction_values) for item in value]
    if isinstance(value, dict):
        return {
            _redact_value(str(key), redaction_values): _redact_value(
                item, redaction_values
            )
            for key, item in value.items()
        }
    return value
