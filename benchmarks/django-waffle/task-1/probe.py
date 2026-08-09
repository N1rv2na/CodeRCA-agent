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
from django.core.management import execute_from_command_line  # noqa: E402
from django.test import SimpleTestCase  # noqa: E402
from waffle.models import Flag  # noqa: E402


class Task1Probe(SimpleTestCase):
    def test_case_17(self) -> None:
        flag = Flag(name="task-1", everyone=False, superusers=True)
        actor = get_user_model()(is_superuser=True)
        self.assertIs(flag.is_active_for_user(actor), False)


if __name__ == "__main__":
    execute_from_command_line([sys.argv[0], "test", "probe", "-v", "1"])
