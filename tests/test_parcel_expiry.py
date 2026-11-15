from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.conf import settings
from django.db import connection
from django.utils import timezone
from django_tenants.utils import tenant_context

from config import celery_app
from lockers.models import Compartment, CompartmentSize, Locker
from organizations.tenancy import OrganizationJobsFailed
from parcels import expiry
from parcels.expiry import expire_all_organizations, expire_overdue_parcels
from parcels.models import Parcel, ParcelEvent, ParcelStatus
from parcels.services import (
    NoFreeCompartment,
    create_parcel,
    deposit_parcel,
    issue_pickup_code,
)
from parcels.state_machine import transition
from parcels.tasks import expire_overdue_parcels_task

pytestmark = pytest.mark.django_db(transaction=True)

S = ParcelStatus
PHONE = "+989123456781"
EXPIRABLE = [S.CREATED, S.STORED, S.READY_FOR_PICKUP, S.PICKUP_FAILED]


def build_world(organization):
    with tenant_context(organization):
        locker = Locker.objects.create(code="main", name="Main hall")
        Compartment.objects.create(locker=locker, number=1, size=CompartmentSize.SMALL)
    return SimpleNamespace(org=organization, locker=locker)


@pytest.fixture
def world(make_org):
    return build_world(make_org("acme"))


def make_parcel(world, status, *, overdue=True):
    """A parcel in `status`, walked there through the real transitions."""
    with tenant_context(world.org):
        parcel = create_parcel(
            locker=world.locker,
            recipient_phone=PHONE,
            size=CompartmentSize.SMALL,
            actor="test",
        )
        if status != S.CREATED:
            deposit_parcel(parcel.pk, actor="test")
        if status in (S.READY_FOR_PICKUP, S.PICKUP_IN_PROGRESS, S.PICKUP_FAILED, S.DELIVERED):
            issue_pickup_code(parcel.pk, actor="test")
        if status in (S.PICKUP_IN_PROGRESS, S.PICKUP_FAILED, S.DELIVERED):
            transition(parcel.pk, S.PICKUP_IN_PROGRESS, actor="test")
        if status in (S.PICKUP_FAILED, S.DELIVERED):
            transition(parcel.pk, status, actor="test")
        offset = timedelta(days=-1) if overdue else timedelta(days=1)
        Parcel.objects.filter(pk=parcel.pk).update(expires_at=timezone.now() + offset)
    return parcel.pk


def status_of(world, parcel_id):
    with tenant_context(world.org):
        return Parcel.objects.get(pk=parcel_id).status


def run_expiry(world):
    with tenant_context(world.org):
        return expire_overdue_parcels()


@pytest.mark.parametrize("status", EXPIRABLE)
def test_an_overdue_parcel_expires(world, status):
    parcel_id = make_parcel(world, status)
    assert run_expiry(world) == 1
    assert status_of(world, parcel_id) == S.EXPIRED


def test_a_parcel_that_is_not_due_yet_is_left_alone(world):
    parcel_id = make_parcel(world, S.READY_FOR_PICKUP, overdue=False)
    assert run_expiry(world) == 0
    assert status_of(world, parcel_id) == S.READY_FOR_PICKUP


@pytest.mark.parametrize("status", [S.PICKUP_IN_PROGRESS, S.DELIVERED])
def test_a_parcel_in_pickup_or_delivered_is_never_expired(world, status):
    parcel_id = make_parcel(world, status)
    assert run_expiry(world) == 0
    assert status_of(world, parcel_id) == status


def test_expiry_is_recorded_as_an_event_by_the_system(world):
    parcel_id = make_parcel(world, S.STORED)
    run_expiry(world)
    with tenant_context(world.org):
        event = ParcelEvent.objects.filter(parcel_id=parcel_id).order_by("id").last()
    assert event.from_status == S.STORED
    assert event.to_status == S.EXPIRED
    assert event.actor == "system"


def test_an_expired_parcel_frees_its_compartment(world):
    make_parcel(world, S.STORED)
    with tenant_context(world.org):
        waiting = create_parcel(
            locker=world.locker,
            recipient_phone=PHONE,
            size=CompartmentSize.SMALL,
            actor="test",
        )
        with pytest.raises(NoFreeCompartment):
            deposit_parcel(waiting.pk, actor="test")
    run_expiry(world)
    with tenant_context(world.org):
        assert deposit_parcel(waiting.pk, actor="test").status == S.STORED


def test_running_twice_expires_each_parcel_once(world):
    parcel_id = make_parcel(world, S.STORED)
    assert run_expiry(world) == 1
    assert run_expiry(world) == 0
    with tenant_context(world.org):
        events = ParcelEvent.objects.filter(parcel_id=parcel_id, to_status=S.EXPIRED)
        assert events.count() == 1


def test_a_pickup_that_wins_the_race_is_not_overridden(world, monkeypatch):
    parcel_id = make_parcel(world, S.READY_FOR_PICKUP)
    real = expiry.transition

    def pickup_takes_the_lock_first(target_id, to_status, **kwargs):
        transition(target_id, S.PICKUP_IN_PROGRESS, actor="customer:1")
        return real(target_id, to_status, **kwargs)

    monkeypatch.setattr(expiry, "transition", pickup_takes_the_lock_first)
    assert run_expiry(world) == 0
    assert status_of(world, parcel_id) == S.PICKUP_IN_PROGRESS
    with tenant_context(world.org):
        events = ParcelEvent.objects.filter(parcel_id=parcel_id, to_status=S.EXPIRED)
        assert not events.exists()


def test_every_organization_is_visited(world, make_org):
    other = build_world(make_org("globex"))
    mine = make_parcel(world, S.STORED)
    theirs = make_parcel(other, S.CREATED)
    assert expire_all_organizations() == {"acme": 1, "globex": 1}
    assert status_of(world, mine) == S.EXPIRED
    assert status_of(other, theirs) == S.EXPIRED
    assert connection.schema_name == "public"


def test_an_organization_that_fails_is_reported_after_the_others_were_done(
    world, make_org, monkeypatch
):
    other = build_world(make_org("globex"))
    mine = make_parcel(world, S.STORED)
    theirs = make_parcel(other, S.STORED)
    real = expiry.expire_overdue_parcels

    def broken_for_acme(**kwargs):
        if connection.tenant.slug == "acme":
            raise RuntimeError("boom")
        return real(**kwargs)

    monkeypatch.setattr(expiry, "expire_overdue_parcels", broken_for_acme)
    with pytest.raises(OrganizationJobsFailed) as caught:
        expire_all_organizations()
    assert caught.value.results == {"globex": 1}
    assert caught.value.failed == ["acme"]
    assert status_of(world, mine) == S.STORED
    assert status_of(other, theirs) == S.EXPIRED
    assert connection.schema_name == "public"


def test_the_task_runs_the_expiry_for_every_organization(world):
    parcel_id = make_parcel(world, S.STORED)
    result = expire_overdue_parcels_task.apply()
    assert result.get() == {"acme": 1}
    assert status_of(world, parcel_id) == S.EXPIRED


def test_the_beat_schedule_points_at_the_registered_task():
    entry = settings.CELERY_BEAT_SCHEDULE["expire-overdue-parcels"]
    assert entry["task"] == expire_overdue_parcels_task.name
    assert entry["task"] in celery_app.tasks
    assert entry["schedule"] > 0


def test_the_task_fails_when_an_organization_fails(world, monkeypatch):
    make_parcel(world, S.STORED)

    def always_broken(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(expiry, "expire_overdue_parcels", always_broken)
    result = expire_overdue_parcels_task.apply()
    assert result.failed()
    assert isinstance(result.result, OrganizationJobsFailed)
