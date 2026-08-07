"""Model boundary used by the walking skeleton."""

from __future__ import annotations

from typing import Protocol

from .contracts import ModelCompletion, TaskManifest


class ModelProvider(Protocol):
    def complete(self, manifest: TaskManifest) -> ModelCompletion:
        """Return a structured completion for a manifest."""


class FakeModelProvider:
    """Deterministic, no-I/O provider for local development and tests."""

    def complete(self, manifest: TaskManifest) -> ModelCompletion:
        return ModelCompletion(
            summary=(
                "Fake model completed the walking-skeleton diagnosis for "
                f"task {manifest.task_id}; no root-cause candidates were produced."
            )
        )
