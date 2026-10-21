"""Author-owned Task 3 probe; never copied into the Agent workspace."""
# ruff: noqa: E402
import sys

from django.conf import settings

settings.configure(
    SECRET_KEY="task-3",
    INSTALLED_APPS=["django.contrib.auth", "django.contrib.contenttypes", "waffle"],
    DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
import django

django.setup()
from django.contrib.auth.models import AnonymousUser
from django.db import connection
from django.http import Http404, HttpRequest, HttpResponse
from waffle import flag_is_active
from waffle.decorators import waffle_flag
from waffle.models import Flag

with connection.schema_editor() as editor:
    editor.create_model(Flag)
Flag.objects.create(name="new-dashboard", everyone=False)
request = HttpRequest()
request.user = AnonymousUser()
direct = flag_is_active(request, "new-dashboard")
try:
    waffle_flag("!new-dashboard")(lambda _: HttpResponse())(request)
    inverse_denied = False
except Http404:
    inverse_denied = True

if direct is not False or inverse_denied:
    print("CRCA_TASK_3_EXPECTED_ASSERTION_MISMATCH")
    print(f"direct_flag_state={direct}")
    print(f"inverse_guard_denied={inverse_denied}")
    sys.exit(1)
print("CRCA_TASK_3_OK")
