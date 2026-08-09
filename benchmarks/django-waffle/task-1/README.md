# CRCA-002 Task 1: django-waffle

This directory defines the first frozen Diagnosis Task. The repository source
is the BSD-3-Clause licensed [django-waffle](https://github.com/django-waffle/django-waffle)
v5.0.0 snapshot (`2ca9a74a90957c79322d6a9b063213258feff908`). The supplied
`task-1.bundle` contains that base commit and the synthetic Faulty Commit
`51e2424a0a6d8817291e5696b0cfbb1b3384a699`, whose commit message is intentionally
opaque and whose diff contains exactly one source-line change.

The bundle is the offline materialization mechanism. It contains the complete
upstream history required by Git and avoids network access during task setup.

The Agent-visible Task Manifest is `manifest.json`; Evaluation-only Ground Truth
is `ground_truth.json` and is deliberately separate. The visible CI artifact is
`ci/task-1-failure.log`; it contains only an opaque test identifier and generic
assertion mismatch, not the Root Symbol, reference repair, fixed source, or an
answer-bearing commit message.

The sole registered command ID is `django_waffle_task_1_v1`. CodeRCA resolves it
to the fixed benchmark-only `probe.py`; callers cannot supply
an arbitrary shell command. The probe uses no database, external service,
randomness, percentage rollout, or concurrency.

Runtime pins are Python 3.11, Django 5.2.16, asgiref 3.9.2, and sqlparse 0.5.4;
wheel hashes are recorded in `requirements.lock`. `Dockerfile` builds the
Manifest image `coderca/django-waffle-task-1:5.0.0-py311-v1` from the pinned
official base image
`python:3.11-slim-bookworm@sha256:b18992999dbe963a45a8a4da40ac2b1975be1a776d939d098c647482bcad5cba`.

Build it from this directory with:

```text
docker build -t coderca/django-waffle-task-1:5.0.0-py311-v1 .
```

To materialize and execute the task from a configured Python environment:

```text
materialize_task_1(<empty-directory>)
run_registered_command(<checkout>, "django_waffle_task_1_v1")
```

The expected Faulty Commit result is a non-zero exit with the sanitized
`assertion_mismatch` manifestation. Run it three times for the CRCA-002
reproducibility acceptance check.
