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
The diff is intentionally not obfuscated. A diff-only successful diagnosis is
valid Outcome evidence, but does not demonstrate search capability. This old
frozen task is retained; a redesigned exploration task is separate future work.

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
The acceptance command exits 0 when the automatic Outcome checks pass without
audit errors, otherwise 1. Add `--require-search` to additionally require a
demonstrated search contribution; it does not change the default Outcome rules.
Even exit 0 requires the human causal review below. It is not a generic Evaluation
Harness, model-quality score, or proof of semantic correctness.

## Acceptance and audit

The checker requires the exact frozen Manifest, a Supported Hypothesis, an
independent final `root_cause_analysis.location` at `waffle/utils.py`, symbol
`keyfmt` (or `waffle.utils.keyfmt`), with a range overlapping faulty line 25,
and passing Public Validation. The initial Hypothesis symbol is not the final
location oracle. Location references must resolve direct Evidence of the
supported Hypothesis or historical Evidence explicitly listed in its Evidence
Basis. The source must be real code/diff Evidence or a matched, untruncated
`search_code(content)` match covering the same path and coordinates. Historical
Evidence keeps its original direction and does not become current-H causal
support. Path search, zero results, truncated matches, unrelated history and
non-covering matches are rejected. Experiment/Observation/Tool Result artifacts
are audited. Missing legacy location is read as null, never inferred from Hypothesis.

Results separate `location` (hit/miss/not_provided), `repair_validation`
(passed/failed/not_run), `causal_review` (required), and `search_capability`
(verified/not_demonstrated/invalid_trajectory). Search verification requires a
real matched result whose Evidence ID was used in an assessment, Reformulation
Evidence Basis, or final location. Free-text-only use is not automatically proven.
No search yields not_demonstrated, not a failed Outcome. Broken references yield
an explicit audit error, never a silent pass. Human causal review is still needed.

Human review must check all four causal fields against `ground_truth.json`:

1. Case-distinct names are separate database identities; isolated lookups pass.
2. Lowercasing in `keyfmt` makes their cache identities identical.
3. The second `Switch.get` reads the first object's cached state.
4. The proposed repair preserves case and passes both lookup orders.

Also inspect search query/results, code Evidence, and assessment references:
search matches alone are not Ground Truth, and an unused search is not a pass.
Fake-provider tests exercise search→read, read→search and read-only with real tools;
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

## Diagnosis decision repair checks (2026-10-19)

Subsequent general diagnosis fixes add application-to-provider request snapshots
under `model-requests/` (including correction attempts), bounded Observation
excerpts for assessment, and explicit historical Evidence Basis knowledge for
experiment selection. No Task 2-specific tool order or prompt answer was added.

- Intermediate run `66d9d6f9-ebc3-423b-8128-5c67bfcc68bd` stopped at the Tool Budget;
  it did not establish successful diagnosis.
- Final run `6222a3df-56a1-4211-8c74-c9595d3c3594` followed the helper into
  `waffle/utils.py` and identified lowercasing. However, E3 was contradicting,
  while assessment requested support from E3. The program rejected the direction
  mismatch. The correction added forbidden `evidence_refs_note`, ending in
  `schema_failure`. This is still a failed acceptance, not a repaired result.
- Inspect `model-requests/10-assess-hypothesis.json` and
  `model-requests/11-assess-hypothesis.json` together with their referenced
  responses. Known provider credentials are redacted, but code/log snippets can
  still contain sensitive repository data; do not publish raw Run directories.

Direction-reference clarification was then checked in run
`af6c03bf-39fc-44e1-94d0-1cd317c58fda`: E2 classified the observed lowercasing
as supporting H2, and assessment supported H2 without schema correction. This
single run did not reproduce the Evidence/Assessment direction conflict. It is
not overall acceptance: root remained `Switch._cache_key`, H1 rejection still
over-interpreted the caller, and the generated patch again had corrupt hunk
counts (`corrupt patch at line 10`). No Evidence was automatically relabelled.

## Tool Budget 10 live regression (2026-10-20)

Run `cc5a9f94-6331-45ef-ad5d-be342977ef11` used three diagnostic Experiments
and one Patch Validation action (4/10 Tool Budget). It rejected H1, formed H2
from E1, searched `def keyfmt`, recorded the observed `v.lower()` as supporting
E3, and supported H2. The deterministic Patch Compiler produced the correct
`waffle/utils.py` replacement; Docker static check and the registered Task 2
test both exited 0.

The persisted run remains **not accepted** because it was produced under the
original ADR-0016 contract. Both final report attempts named
`waffle/utils.py::keyfmt` at lines 20–25 but cited only E3 from `search_code`;
the former validator required covering `read_code` or diff Evidence, so the run
ended in `schema_failure`. Under the revised ADR-0016 contract, an offline replay
of the unchanged first report response passes final-location validation: E3 is a
`matched` content search whose untruncated `waffle/utils.py` match covers lines
15–25 and whose provenance resolves through the recorded Experiment, Tool Result,
Observation and Artifact. The historical `report.json` is intentionally not
rewritten, and no second live model run was performed.

## Evidence Basis location acceptance (2026-10-20)

After ADR-0016 was amended to separate Hypothesis-relative Evidence direction
from audited source-coordinate provenance, run
`7c40fa56-d099-4578-ba16-90aea2940516` completed successfully. H1 ended
inconclusive after three Experiments; H2 explicitly inherited E1–E3, gathered
its own Supporting Evidence, identified `waffle/utils.py::keyfmt`, and produced
the reference repair. Static and registered-test Validation both passed.

The final location covers lines 22–26 and cites E1 from H2's explicit Evidence
Basis together with direct H2 Evidence E5/E6. Historical Evidence kept its H1
identity and original direction. The acceptance checker exited 0 with
`location=hit`, `repair_validation=passed`, `search_capability=verified`, and
`outcome_pass=true`; human causal review remains required. The run used seven
of ten Tool calls. It also repeated one `read_code` Experiment and needed one
Assessment schema correction after reaching the per-Hypothesis Experiment
limit, so the successful Outcome is not evidence of an optimal trajectory.
