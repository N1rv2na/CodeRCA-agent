# Task 2 — Code Exploration & Root Cause Localization

Author-only benchmark directory. Do not mount this directory into the Agent
workspace or add Ground Truth / reference repair to model context.

## Frozen inputs

- Upstream: django-waffle v5.0.0, same base and image as Task 1.
- Faulty Commit: `30c21019633ddd5e60d3628c08692e404ea03d55`.
- Bundle contains the upstream base and this independent synthetic commit.
- Manifest permits business-source reads/writes under `waffle/`; it does not
  reveal the exact faulty file. The normal runtime security checks still apply.
- `probe.py` is the author-owned registered `python -c` payload. It creates an
  in-memory database and real Django local cache, with no mocked Waffle behavior.
  Its exact source is frozen in `registered-command.json`, outside the checkout.
- The Task 1 image is reused without rebuilding. No new dependencies.

Two case-distinct switches with opposite states behave correctly in isolation,
but interfere when queried consecutively. The initial CI log exposes behavior,
not a canonical root symbol or file. Search can trace `switch_is_active`,
`_cache_key`, and `keyfmt`; code reading reveals lowercasing before hashing.
The diff is intentionally not obfuscated. Merely reading that diff does not
satisfy this task's search-trajectory acceptance requirement.

## Reproduce

From the project root, after installing dev dependencies and building the Task 1
image using its README:

```bash
.venv/bin/python -m pytest tests/test_task_2.py -q
WORKSPACE=$(.venv/bin/python - <<'PY'
import tempfile
from pathlib import Path
from coderca.benchmark import materialize_task_2
root = Path(tempfile.mkdtemp(prefix="coderca-task2-"))
print(materialize_task_2(root / "workspace"))
PY
)
.venv/bin/python -m coderca.model_gate_cli \
  --output-directory .coderca-model-gate/task-2
.venv/bin/coderca benchmarks/django-waffle/task-2/manifest.json \
  --runs-dir .coderca-runs --model-provider openai-compatible \
  --workspace "$WORKSPACE"
.venv/bin/python -m coderca.task_2_acceptance .coderca-runs/<run-id>
```

Use existing explicit model environment configuration; do not place secrets in
this directory. A completed Diagnosis Run is not necessarily a successful repair.
The acceptance command exits 1 on structural failure, 0 on structural pass.
Even exit 0 requires the human causal review below. It is not a generic Evaluation
Harness, model-quality score, or proof of semantic correctness.

## Acceptance and audit

The checker requires the exact frozen Manifest, supported final root `keyfmt`
(also accepts the explicitly enumerated qualified name `waffle.utils.keyfmt`),
an applied patch with passing Public Validation, and artifact-backed search and
code/diff Evidence referenced by the final supported assessment. It verifies
Experiment/Hypothesis/Observation/Tool Result provenance without prescribing order.
Reformulation Evidence Basis references are followed into earlier Hypotheses.
If search only guides a later Experiment through free-text reasoning rather than
structured references, the checker reports `not_proven_by_structured_refs` and
requires human review; it does not claim that search had no causal contribution.

Human review must check all four causal fields against `ground_truth.json`:

1. Case-distinct names are separate database identities; isolated lookups pass.
2. Lowercasing in `keyfmt` makes their cache identities identical.
3. The second `Switch.get` reads the first object's cached state.
4. The proposed repair preserves case and passes both lookup orders.

Also inspect search query/results, code Evidence, and assessment references:
search matches alone are not Ground Truth, and an unused search is not a pass.
Fake-provider tests exercise both search→read and read→search with real tools;
only the Docker process boundary is replaced in those default tests. They are
contract tests, not evidence of model reasoning. Local probe tests separately
check base pass, faulty fail three times, and reference repair pass.

## Recorded live check (2026-10-19)

- Configured `deepseek-flash` passed the model gate.
- Same Docker image: Base probe exit 0; Faulty probe exit 1 with expected marker.
- Reference repair applied through the real Tool Runtime passed Docker static
  check and registered test (both exit 0), completing the three-part invariant.
- Run `e45248a5-59a1-4f2a-8265-210640698ee0` performed two real searches and a
  code read, rejected H1 and supported H2 using accumulated evidence.
- **Not accepted**: final root remained `Switch`, not `keyfmt`. The model's repair
  mechanism identified the lowercasing defect, but its unified diff had invalid
  hunk counts (`corrupt patch at line 10`), so Public Validation failed before tests.
- Full local artifacts remain in the ignored `.coderca-runs/<run-id>/`; no API
  credentials or raw provider responses are committed here.

The successful real-model acceptance criterion remains open. This ticket does not
change immutable Hypothesis identity, introduce patch retry/repair, force search,
or change prompts to obtain a passing demonstration.
