from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.conf import settings
from django.db import connection
from django.utils import timezone
from django_tenants.utils import tenant_context

from config import celery_app
from lockers.models import Compartment, CompartmentSize, Locker
from parcels import recovery
from parcels.models import Parcel, ParcelEvent, ParcelStatus
from parcels.recovery import recover_all_organizations, recover_stuck_pickups
from parcels.services import create_parcel, deposit_parcel, issue_pickup_code
from parcels.state_machine import transition
from parcels.tasks import recover_stuck_pickups_task

pytestmark = pytest.mark.django_db(transaction=True)

S = ParcelStatus
PHONE = "+989123456781"


def build_world(organization):
    with tenant_context(organization):
        locker = Locker.objects.create(code="main", name="Main hall")
        Compartment.objects.create(locker=locker, number=1, size=CompartmentSize.SMALL)
    return SimpleNamespace(org=organization, locker=locker)


@pytest.fixture
def world(make_org):
    return build_world(make_org("acme"))


def parcel_since(world, *, minutes_ago=30, status=S.PICKUP_IN_PROGRESS):
    """A parcel that has been in `status` for `minutes_ago` minutes."""
    with tenant_context(world.org):
        parcel = create_parcel(
            locker=world.locker,
            recipient_phone=PHONE,
            size=CompartmentSize.SMALL,
            actor="test",
        )
        deposit_parcel(parcel.pk, actor="test")
        issue_pickup_code(parcel.pk, actor="test")
        if status == S.PICKUP_IN_PROGRESS:
            transition(parcel.pk, S.PICKUP_IN_PROGRESS, actor="test")
        # A queryset update skips auto_now, so the time is exactly what we set.
        Parcel.objects.filter(pk=parcel.pk).update(
            updated_at=timezone.now() - timedelta(minutes=minutes_ago)
        )
    return parcel.pk


def load(world, parcel_id):
    with tenant_context(world.org):
        return Parcel.objects.get(pk=parcel_id)


def run_recovery(world):
    with tenant_context(world.org):
        return recover_stuck_pickups()


def test_a_pickup_that_never_finished_is_failed(world):
    parcel_id = parcel_since(world)
    assert run_recovery(world) == 1
    assert load(world, parcel_id).status == S.PICKUP_FAILED


def test_a_pickup_that_is_still_fresh_is_left_alone(world):
    parcel_id = parcel_since(world, minutes_ago=0)
    assert run_recovery(world) == 0
    assert load(world, parcel_id).status == S.PICKUP_IN_PROGRESS


def test_the_time_limit_comes_from_the_settings(world, settings):
    parcel_id = parcel_since(world, minutes_ago=30)
    settings.PICKUP_RECOVERY_MINUTES = 60
    assert run_recovery(world) == 0
    settings.PICKUP_RECOVERY_MINUTES = 5
    assert run_recovery(world) == 1
    assert load(world, parcel_id).status == S.PICKUP_FAILED


def test_an_old_parcel_in_another_state_is_left_alone(world):
    parcel_id = parcel_since(world, status=S.READY_FOR_PICKUP)
    assert run_recovery(world) == 0
    assert load(world, parcel_id).status == S.READY_FOR_PICKUP


def test_recovery_is_recorded_as_an_event_by_the_system(world):
    parcel_id = parcel_since(world)
    run_recovery(world)
    with tenant_context(world.org):
        event = ParcelEvent.objects.filter(parcel_id=parcel_id).order_by("id").last()
    assert event.from_status == S.PICKUP_IN_PROGRESS
    assert event.to_status == S.PICKUP_FAILED
    assert event.actor == "system"
    assert "door state unknown" in event.reason


def test_a_recovered_pickup_counts_as_a_failed_attempt(world):
    parcel_id = parcel_since(world)
    run_recovery(world)
    assert load(world, parcel_id).pickup_attempts == 1


def test_a_recovered_parcel_can_be_sent_a_new_code(world):
    parcel_id = parcel_since(world)
    run_recovery(world)
    with tenant_context(world.org):
        issue_pickup_code(parcel_id, actor="operator")
    assert load(world, parcel_id).status == S.READY_FOR_PICKUP


def test_running_twice_recovers_each_parcel_once(world):
    parcel_id = parcel_since(world)
    assert run_recovery(world) == 1
    assert run_recovery(world) == 0
    with tenant_context(world.org):
        events = ParcelEvent.objects.filter(parcel_id=parcel_id, to_status=S.PICKUP_FAILED)
        assert events.count() == 1


def test_a_pickup_that_finishes_first_is_not_overridden(world, monkeypatch):
    parcel_id = parcel_since(world)
    real = recovery.transition

    def pickup_finishes_first(target_id, to_status, **kwargs):
        transition(target_id, S.DELIVERED, actor="device", reason="door opened")
        return real(target_id, to_status, **kwargs)

    monkeypatch.setattr(recovery, "transition", pickup_finishes_first)
    assert run_recovery(world) == 0
    assert load(world, parcel_id).status == S.DELIVERED


def test_every_organization_is_visited(world, make_org):
    other = build_world(make_org("globex"))
    mine = parcel_since(world)
    theirs = parcel_since(other)
    assert recover_all_organizations() == {"acme": 1, "globex": 1}
    assert load(world, mine).status == S.PICKUP_FAILED
    assert load(other, theirs).status == S.PICKUP_FAILED
    assert connection.schema_name == "public"


def test_the_task_runs_the_recovery_for_every_organization(world):
    parcel_id = parcel_since(world)
    result = recover_stuck_pickups_task.apply()
    assert result.get() == {"acme": 1}
    assert load(world, parcel_id).status == S.PICKUP_FAILED


def test_the_beat_schedule_points_at_the_registered_task():
    entry = settings.CELERY_BEAT_SCHEDULE["recover-stuck-pickups"]
    assert entry["task"] == recover_stuck_pickups_task.name
    assert entry["task"] in celery_app.tasks
    assert entry["schedule"] > 0
