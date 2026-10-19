"""Author-owned Task 2 regression probe; never copied into the agent workspace."""
import sys

from django.conf import settings

settings.configure(
    SECRET_KEY="coderca-task-2",
    INSTALLED_APPS=["django.contrib.auth", "django.contrib.contenttypes", "waffle"],
    DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
    USE_TZ=True,
)
import django

django.setup()
from django.core.cache import cache
from django.db import connection
from waffle import switch_is_active
from waffle.models import Switch

with connection.schema_editor() as editor:
    editor.create_model(Switch)
Switch.objects.create(name="Checkout", active=False)
Switch.objects.create(name="checkout", active=True)

try:
    for name, expected in [("Checkout", False), ("checkout", True)]:
        cache.clear()
        assert switch_is_active(name) == expected, "isolated lookup differs"
    for first, second in [("Checkout", "checkout"), ("checkout", "Checkout")]:
        cache.clear()
        expected = {"Checkout": False, "checkout": True}
        assert switch_is_active(first) == expected[first], "first lookup differs"
        assert switch_is_active(second) == expected[second], "second lookup differs"
except AssertionError:
    print("CRCA_TASK_2_EXPECTED_ASSERTION_MISMATCH")
    print("Two persisted switches, Checkout=False and checkout=True, behave correctly")
    print("when queried independently after clearing the cache. Querying both in")
    print("sequence returns the first switch's state for the second name.")
    sys.exit(1)
print("CRCA_TASK_2_OK")
