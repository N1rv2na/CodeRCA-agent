"""Opaque, fixed Task 1 regression probe.

This file is an explicit benchmark-only dependency, not part of the CodeRCA
runtime package. Its test identifier intentionally carries no Root Symbol or
repair text.
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "test_settings")

import django  # noqa: E402

django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from waffle.models import Flag  # noqa: E402

EXPECTED_FAILURE_MARKER = "CRCA_TASK_1_EXPECTED_ASSERTION_MISMATCH"


def main() -> int:
    flag = Flag(name="task-1", everyone=False, superusers=True)
    actor = get_user_model()(is_superuser=True)
    if flag.is_active_for_user(actor) is not False:
        print(EXPECTED_FAILURE_MARKER, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
