from __future__ import annotations

from pathlib import Path

import pytest

from coderca.model_provider import PersistenceSafeModelArtifact
from coderca.run_store import RunStore


@pytest.mark.parametrize("attempt", [-1, 0, 3])
def test_hypothesis_formation_response_rejects_unbounded_attempt_numbers(
    attempt: int, tmp_path: Path
) -> None:
    store = RunStore(tmp_path / "runs")
    artifacts = store.create_run("run-001")

    with pytest.raises(ValueError, match="attempt must be 1 or 2"):
        store.write_hypothesis_formation_response(
            artifacts,
            attempt=attempt,
            response=PersistenceSafeModelArtifact({"content": "safe"}),
        )

    assert not artifacts.model_responses_directory.exists()
