"""Model boundaries for the deterministic skeleton and Gemini gate.

The Gemini adapter deliberately has a small, synchronous seam.  Keeping the
transport injectable makes the compatibility gate testable without a network
connection and keeps the existing CRCA-001 provider contract intact.
"""

from __future__ import annotations

import copy
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from .contracts import ModelCompletion, TaskManifest

if TYPE_CHECKING:
    from .model_gate import GateResult


class ModelProvider(Protocol):
    def ensure_ready(self) -> None:
        """Reject use before provider-specific readiness checks pass."""

    def complete(self, manifest: TaskManifest) -> ModelCompletion:
        """Return a structured completion for a manifest."""


class FakeModelProvider:
    """Deterministic, no-I/O provider for local development and tests."""

    def ensure_ready(self) -> None:
        """The deterministic provider has no external readiness dependency."""

    def complete(self, manifest: TaskManifest) -> ModelCompletion:
        return ModelCompletion(
            summary=(
                "Fake model completed the walking-skeleton diagnosis for "
                f"task {manifest.task_id}; no root-cause candidates were produced."
            )
        )


GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
GEMINI_MODEL = "gemini-3.6-flash"
GEMINI_API_KEY_ENV = "GEMINI_API_KEY"


class GeminiErrorCategory(str, Enum):
    """Stable categories for failures at the external model boundary."""

    MISSING_CREDENTIALS = "missing_credentials"
    AUTHENTICATION = "authentication"
    PERMISSION = "permission"
    QUOTA = "quota"
    RATE_LIMIT = "rate_limit"
    MODEL_UNAVAILABLE = "model_unavailable"
    NETWORK = "network"
    TIMEOUT = "timeout"
    INVALID_RESPONSE = "invalid_response"


class GeminiProviderError(RuntimeError):
    """A non-secret, machine-classifiable Gemini provider failure."""

    def __init__(
        self,
        category: GeminiErrorCategory,
        message: str,
        *,
        status_code: int | None = None,
    ) -> None:
        self.category = category
        self.status_code = status_code
        self.message = message
        super().__init__(message)

    def __repr__(self) -> str:
        return (
            f"GeminiProviderError(category={self.category.value!r}, "
            f"message={self.message!r}, status_code={self.status_code!r})"
        )


class GeminiGateRequiredError(RuntimeError):
    """Raised when diagnosis use is attempted before a passing gate."""


@dataclass(frozen=True)
class TransportRequest:
    """HTTP request passed to the injected transport."""

    url: str
    headers: dict[str, str]
    json_body: dict[str, Any]
    timeout_seconds: float


@dataclass(frozen=True)
class TransportResponse:
    """Minimal HTTP response needed by the adapter."""

    status_code: int
    body: str


class GeminiTransport(Protocol):
    def request(self, request: TransportRequest) -> TransportResponse:
        """Execute one HTTP request."""


@dataclass(frozen=True)
class ProviderResponse:
    """Validated model content plus opaque provider response metadata."""

    content: dict[str, Any]
    raw_response: dict[str, Any]
    assistant_message: dict[str, Any]
    provider_metadata: dict[str, Any]


class UrllibGeminiTransport:
    """Small stdlib HTTPS transport used only by an explicit real gate run."""

    def request(self, request: TransportRequest) -> TransportResponse:
        encoded = json.dumps(request.json_body).encode("utf-8")
        http_request = urllib.request.Request(
            request.url,
            data=encoded,
            headers=request.headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                http_request, timeout=request.timeout_seconds
            ) as result:
                return TransportResponse(
                    status_code=int(result.status),
                    body=result.read().decode("utf-8"),
                )
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            return TransportResponse(status_code=error.code, body=body)


class GeminiModelProvider:
    """The one supported real model provider, fixed to Gemini Developer API."""

    def __init__(
        self,
        *,
        transport: GeminiTransport | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._api_key = os.environ.get(GEMINI_API_KEY_ENV)
        self._transport = transport or UrllibGeminiTransport()
        self._timeout_seconds = timeout_seconds
        self._gate_passed = False

    @property
    def model(self) -> str:
        return GEMINI_MODEL

    @property
    def base_url(self) -> str:
        return GEMINI_BASE_URL

    @property
    def generation_config(self) -> dict[str, Any]:
        return {
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }

    def __repr__(self) -> str:
        return (
            "GeminiModelProvider(base_url="
            f"{GEMINI_BASE_URL!r}, model={GEMINI_MODEL!r}, "
            f"timeout_seconds={self._timeout_seconds!r})"
        )

    def preflight(self) -> ProviderResponse:
        """Perform one minimal request before any compatibility probe."""

        return self._request_json(
            "Return this JSON object exactly: {\"preflight\": true}."
        )

    def complete(self, manifest: TaskManifest) -> ModelCompletion:
        """Preserve the CRCA-001 synchronous provider interface."""

        self.ensure_ready()

        result = self.complete_json(
            "Return a finalizing completion JSON object with a non-empty summary "
            f"for public diagnosis task {manifest.task_id}."
        )
        try:
            return ModelCompletion.model_validate(result.content)
        except Exception as error:
            raise GeminiProviderError(
                GeminiErrorCategory.INVALID_RESPONSE,
                "Gemini response did not satisfy ModelCompletion schema",
            ) from error

    def complete_json(
        self,
        prompt: str,
        *,
        continuation: ProviderResponse | None = None,
        response_schema: dict[str, Any] | None = None,
    ) -> ProviderResponse:
        """Request structured JSON only after this instance passes its gate."""

        self.ensure_ready()
        return self._request_json(
            prompt,
            continuation=continuation,
            response_schema=response_schema,
        )

    def _request_json(
        self,
        prompt: str,
        *,
        continuation: ProviderResponse | None = None,
        response_schema: dict[str, Any] | None = None,
    ) -> ProviderResponse:
        """Issue one HTTPS request behind diagnosis and gate entry points."""

        if not self._api_key:
            raise GeminiProviderError(
                GeminiErrorCategory.MISSING_CREDENTIALS,
                f"{GEMINI_API_KEY_ENV} is not configured",
            )
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": prompt},
        ]
        if continuation is not None:
            messages.insert(0, copy.deepcopy(continuation.assistant_message))
        body: dict[str, Any] = {
            "model": GEMINI_MODEL,
            "messages": messages,
            **copy.deepcopy(self.generation_config),
        }
        if response_schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "coderca_probe",
                    "strict": True,
                    "schema": copy.deepcopy(response_schema),
                },
            }
        request = TransportRequest(
            url=f"{GEMINI_BASE_URL}chat/completions",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json_body=body,
            timeout_seconds=self._timeout_seconds,
        )
        try:
            response = self._transport.request(request)
        except TimeoutError as error:
            raise GeminiProviderError(
                GeminiErrorCategory.TIMEOUT,
                "Gemini request timed out",
            ) from error
        except (OSError, ConnectionError) as error:
            raise GeminiProviderError(
                GeminiErrorCategory.NETWORK,
                "Gemini request could not reach the service",
            ) from error
        return self._parse_response(response)

    def run_compatibility_gate(self, output_directory: Path) -> GateResult:
        """Run the only workflow allowed to authorize this provider instance."""

        from .model_gate import GeminiCompatibilityGate

        result = GeminiCompatibilityGate(_GeminiGateSession(self)).run(
            output_directory
        )
        if result.compatible:
            self._gate_passed = True
        return result

    def ensure_ready(self) -> None:
        """Reject diagnosis use until this provider instance passes the gate."""

        if not self._gate_passed:
            raise GeminiGateRequiredError(
                "Gemini compatibility gate has not passed for this provider"
            )

    def _parse_response(self, response: TransportResponse) -> ProviderResponse:
        if response.status_code < 200 or response.status_code >= 300:
            raise self._http_error(response)
        try:
            raw = json.loads(response.body)
            if not isinstance(raw, dict):
                raise ValueError("response root is not an object")
            choices = raw["choices"]
            message = choices[0]["message"]
            content = message["content"]
            if not isinstance(message, dict) or not isinstance(content, str):
                raise ValueError("assistant message has invalid shape")
            decoded = json.loads(content)
            if not isinstance(decoded, dict):
                raise ValueError("content is not a JSON object")
            if raw.get("model") != GEMINI_MODEL:
                raise GeminiProviderError(
                    GeminiErrorCategory.MODEL_UNAVAILABLE,
                    "Gemini response used an unexpected model",
                    status_code=response.status_code,
                )
        except (
            KeyError,
            IndexError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ) as error:
            raise GeminiProviderError(
                GeminiErrorCategory.INVALID_RESPONSE,
                "Gemini response was not valid structured JSON",
                status_code=response.status_code,
            ) from error
        extra_content = copy.deepcopy(message.get("extra_content", {}))
        if not isinstance(extra_content, dict):
            extra_content = {}
        metadata = {"extra_content": extra_content}
        return ProviderResponse(
            content=decoded,
            raw_response=copy.deepcopy(raw),
            assistant_message=copy.deepcopy(message),
            provider_metadata=metadata,
        )

    @staticmethod
    def _http_error(response: TransportResponse) -> GeminiProviderError:
        body = response.body.lower()
        if response.status_code == 401:
            category = GeminiErrorCategory.AUTHENTICATION
        elif response.status_code == 403:
            category = (
                GeminiErrorCategory.QUOTA
                if "quota" in body or "resource exhausted" in body
                else GeminiErrorCategory.PERMISSION
            )
        elif response.status_code == 404:
            category = GeminiErrorCategory.MODEL_UNAVAILABLE
        elif response.status_code == 429:
            category = (
                GeminiErrorCategory.QUOTA
                if "quota" in body or "resource exhausted" in body
                else GeminiErrorCategory.RATE_LIMIT
            )
        elif response.status_code in {408, 504}:
            category = GeminiErrorCategory.TIMEOUT
        elif response.status_code in {400, 422}:
            category = GeminiErrorCategory.INVALID_RESPONSE
        else:
            category = GeminiErrorCategory.NETWORK
        return GeminiProviderError(
            category,
            f"Gemini request failed ({category.value})",
            status_code=response.status_code,
        )


class _GeminiGateSession:
    """Capability-scoped adapter available only during an explicit gate run."""

    def __init__(self, provider: GeminiModelProvider) -> None:
        self._provider = provider

    def preflight(self) -> ProviderResponse:
        return self._provider.preflight()

    def complete_probe(
        self,
        prompt: str,
        *,
        response_schema: dict[str, Any],
    ) -> ProviderResponse:
        return self._provider._request_json(
            prompt, response_schema=response_schema
        )
