# Task 3 — Bounded Self-Correction

Author-only benchmark directory. Do not mount this directory into the Agent
workspace or add Ground Truth, the reference repair, or the probe source to
model context.

## Frozen task

- Upstream: django-waffle v5.0.0 at the same Base Snapshot and Docker image as
  Tasks 1 and 2.
- Faulty Commit: `17f2b840e6f39ef0773abb7b4618acfb9f6a6bc7`.
- The bounded CI excerpt reports only that a legacy endpoint is denied while
  its feature is configured inactive. It preserves the initial triage team's
  explicit but wrong state-resolution mechanism and its falsification condition,
  while withholding the actual direct result, decorator module, and canonical
  Root Symbol. The registered reproduction separates state-resolution and guard
  outcomes, so `run_tests` is an observable discriminating Experiment rather
  than an undisclosed benchmark trick.
- The registered test rerun is intentionally more discriminating: it records
  that the direct evaluator is False while the inverse guard still denies the
  request.

The intended self-correction trajectory is observable rather than a private
reasoning trace: H1 attributes the failure to underlying Flag-state resolution;
the H1-bound registered test produces Contradicting Evidence; the program
rejects H1 before forming H2 from that Evidence ID; H2 identifies the missing
negation in `waffle.decorators.waffle_flag`, then alone enters patch Validation.
Whether a live model's H1 is reasonable and its causal explanation matches the
Ground Truth still requires human review.

## Recorded live checks

- Run `44573c80-14d3-4e38-b9ea-65700ddc15f1` used the original shorter CI
  summary. It inspected diff and searched for a production view that the
  author-owned probe creates dynamically, did not run the registered test until
  H3, and exhausted H1–H3 as inconclusive. This is a failed acceptance, not
  hidden success evidence.
- The CI summary was then clarified only to advertise the registered probe's
  observation capability. No probe outcome, Root Symbol, core Prompt, Schema,
  ContextBuilder, lifecycle rule, or tool policy was changed.
- Run `c2a5c711-1cc6-4f8d-b3b8-1a8951bef152` used that capability note but
  formed an overly broad H1 combining state resolution and guard behavior. It
  reached the correct H2 and passed patch Validation, yet ran the discriminating
  test only for H2; H1 ended inconclusive rather than rejected. The bounded CI
  triage statement was therefore narrowed to one explicit, falsifiable false
  mechanism without revealing the registered observation.
- Run `19406224-f3e0-45b3-8662-01cfb0da0beb` selected `run_tests` for H1 and
  rejected it, but the embedded registered command pushed the final inverse
  guard diagnostic just beyond the 2,000-character Working Context excerpt.
  The author-only probe was shortened and a regression now proves both
  discriminating facts fit the existing bounded projection; the ContextBuilder
  and its limit were not changed.
- Run `396c9d3f-7005-4204-aa61-10b3a307cc56` passed. H1 used `run_tests`, E1
  was Contradicting, H1 became rejected, H2 cited only E1, E2 directly showed
  the missing negation, and only supported H2 produced the candidate patch.
  Static check and registered Validation passed. The acceptance CLI exited 0
  with `h1_falsified=true`, `h2_reformulated=true`, `trajectory_pass=true`, and
  `outcome_pass=true`; human causal review remains explicit.

## Reproduce and accept

```bash
.venv/bin/python -m pytest tests/test_task_3.py -q
WORKSPACE=$(.venv/bin/python - <<'PY'
import tempfile
from pathlib import Path
from coderca.benchmark import materialize_task_3
root = Path(tempfile.mkdtemp(prefix="coderca-task3-"))
print(materialize_task_3(root / "workspace"))
PY
)
.venv/bin/coderca benchmarks/django-waffle/task-3/manifest.json \
  --runs-dir .coderca-runs --model-provider openai-compatible \
  --workspace "$WORKSPACE"
.venv/bin/python -m coderca.task_3_acceptance .coderca-runs/<run-id>
```

The acceptance command checks persisted Outcome and Trajectory contracts and
exits 0 only when both pass. It still reports `human_review_required=true` for
H1 plausibility and final causal correctness. Raw Run directories may contain
repository content and remain local ignored artifacts.
