from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.conf import settings
from django.db import connection
from django.utils import timezone
from django_tenants.utils import tenant_context

from config import celery_app
from idempotency.models import IdempotencyKey
from idempotency.services import execute, purge_expired_keys
from idempotency.tasks import purge_expired_keys_task
from organizations.tenancy import run_in_each_organization

pytestmark = pytest.mark.django_db(transaction=True)


def store_keys(organization):
    """Two stored keys; the first one has expired."""
    with tenant_context(organization):
        for name in ("old", "fresh"):
            execute(
                key=name,
                endpoint="test",
                user_id=1,
                request_data={},
                handler=lambda: (200, {"ok": True}),
            )
        oldest = IdempotencyKey.objects.order_by("pk").first()
        IdempotencyKey.objects.filter(pk=oldest.pk).update(
            expires_at=timezone.now() - timedelta(hours=1)
        )
    return SimpleNamespace(org=organization)


def key_count(world):
    with tenant_context(world.org):
        return IdempotencyKey.objects.count()


@pytest.fixture
def world(make_org):
    return store_keys(make_org("acme"))


def test_an_expired_key_is_deleted_and_a_live_one_is_kept(world):
    with tenant_context(world.org):
        purge_expired_keys()
    assert key_count(world) == 1


def test_every_organization_is_cleaned(world, make_org):
    other = store_keys(make_org("globex"))
    assert run_in_each_organization(purge_expired_keys) == {"acme": 1, "globex": 1}
    assert key_count(world) == 1
    assert key_count(other) == 1
    assert connection.schema_name == "public"


def test_the_task_cleans_every_organization(world):
    result = purge_expired_keys_task.apply()
    assert result.get() == {"acme": 1}
    assert key_count(world) == 1


def test_the_beat_schedule_points_at_the_registered_task():
    entry = settings.CELERY_BEAT_SCHEDULE["purge-expired-idempotency-keys"]
    assert entry["task"] == purge_expired_keys_task.name
    assert entry["task"] in celery_app.tasks
    assert entry["schedule"] > 0
