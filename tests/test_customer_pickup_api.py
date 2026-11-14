from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django_tenants.utils import tenant_context
from rest_framework.test import APIClient

from accounts.throttling import PickupThrottle
from devices.simulator import Fault
from lockers.models import Compartment, CompartmentSize, Locker
from parcels.device import get_device, reset_devices
from parcels.models import Parcel
from parcels.services import create_parcel, deposit_parcel, send_pickup_code

pytestmark = pytest.mark.django_db(transaction=True)

ALICE = "+989123456781"
BOB = "+989123456782"

CUSTOMER_FIELDS = {
    "tracking_code",
    "locker",
    "compartment",
    "size",
    "status",
    "expires_at",
    "created_at",
}


@pytest.fixture(autouse=True)
def fresh_device():
    reset_devices()
    yield
    reset_devices()


@pytest.fixture
def world(make_org, sms_outbox):
    users = get_user_model().objects
    acme = make_org("acme")
    with tenant_context(acme):
        locker = Locker.objects.create(code="main", name="Main hall")
        for number in (1, 2, 3):
            Compartment.objects.create(
                locker=locker, number=number, size=CompartmentSize.SMALL
            )
    return SimpleNamespace(
        org=acme,
        locker=locker,
        outbox=sms_outbox,
        alice=users.create(phone_number=ALICE),
        bob=users.create(phone_number=BOB),
    )


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def new_parcel(world, phone=ALICE):
    with tenant_context(world.org):
        return create_parcel(
            locker=world.locker,
            recipient_phone=phone,
            size=CompartmentSize.SMALL,
            actor="test",
        )


def ready_parcel(world, phone=ALICE):
    """A parcel in a compartment with a pickup code that was texted to `phone`."""
    parcel = new_parcel(world, phone)
    with tenant_context(world.org):
        deposit_parcel(parcel.pk, actor="test")
        send_pickup_code(parcel.pk, actor="test")
    code = world.outbox[-1][1].rsplit(" ", 1)[-1]
    return SimpleNamespace(pk=parcel.pk, tracking_code=parcel.tracking_code, code=code)


def reload(world, parcel):
    with tenant_context(world.org):
        return Parcel.objects.get(pk=parcel.pk)


def wrong(code):
    return ("9" if code[0] != "9" else "8") + code[1:]


def pickup(client, tracking_code, body, key="key-1", org="acme"):
    extra = {} if key is None else {"HTTP_IDEMPOTENCY_KEY": key}
    return client.post(
        f"/api/v1/orgs/{org}/my/parcels/{tracking_code}/pickup/",
        body,
        format="json",
        **extra,
    )


def replayed(response):
    return response.headers.get("Idempotent-Replayed") == "true"


def test_the_right_code_opens_the_door_and_delivers(world):
    parcel = ready_parcel(world)
    response = pickup(client_for(world.alice), parcel.tracking_code, {"code": parcel.code})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == CUSTOMER_FIELDS
    assert body["status"] == "DELIVERED"
    assert reload(world, parcel).status == "DELIVERED"
    device = get_device()
    assert len(device.opened) == 1
    assert device.opened[0][2] == f"{parcel.tracking_code}:1"


def test_a_repeated_request_replays_and_opens_the_door_once(world):
    parcel = ready_parcel(world)
    client = client_for(world.alice)
    first = pickup(client, parcel.tracking_code, {"code": parcel.code})
    second = pickup(client, parcel.tracking_code, {"code": parcel.code})
    assert first.status_code == second.status_code == 200
    assert replayed(second) and not replayed(first)
    assert second.json() == first.json()
    assert len(get_device().opened) == 1


def test_a_wrong_code_is_refused_and_counted(world):
    parcel = ready_parcel(world)
    response = pickup(
        client_for(world.alice), parcel.tracking_code, {"code": wrong(parcel.code)}
    )
    assert response.status_code == 403
    assert response.json()["code"] == "wrong_pickup_code"
    assert response.json()["attempts_left"] == 2
    assert reload(world, parcel).wrong_code_attempts == 1
    assert get_device().calls == 0


def test_a_replayed_wrong_code_is_not_counted_again(world):
    parcel = ready_parcel(world)
    client = client_for(world.alice)
    body = {"code": wrong(parcel.code)}
    pickup(client, parcel.tracking_code, body)
    again = pickup(client, parcel.tracking_code, body)
    assert again.status_code == 403
    assert replayed(again)
    assert reload(world, parcel).wrong_code_attempts == 1


def test_too_many_wrong_codes_block_even_the_right_one(world):
    parcel = ready_parcel(world)
    client = client_for(world.alice)
    for index in range(3):
        pickup(client, parcel.tracking_code, {"code": wrong(parcel.code)}, key=f"k{index}")
    response = pickup(client, parcel.tracking_code, {"code": parcel.code}, key="k-last")
    assert response.status_code == 403
    assert response.json()["code"] == "pickup_blocked"
    assert get_device().calls == 0
    assert reload(world, parcel).status == "READY_FOR_PICKUP"


def test_a_device_fault_is_reported_and_replayed_without_a_second_command(world):
    parcel = ready_parcel(world)
    get_device().inject(Fault.ERROR)
    client = client_for(world.alice)
    first = pickup(client, parcel.tracking_code, {"code": parcel.code})
    assert first.status_code == 502
    assert first.json()["code"] == "device_fault"
    assert first.json()["parcel"]["status"] == "PICKUP_FAILED"
    again = pickup(client, parcel.tracking_code, {"code": parcel.code})
    assert again.status_code == 502
    assert replayed(again)
    assert get_device().calls == 1
    assert reload(world, parcel).status == "PICKUP_FAILED"


def test_a_device_timeout_says_the_door_may_have_opened(world):
    parcel = ready_parcel(world)
    get_device().inject(Fault.TIMEOUT, opened=True)
    response = pickup(client_for(world.alice), parcel.tracking_code, {"code": parcel.code})
    assert response.status_code == 504
    assert response.json()["code"] == "device_timeout"
    assert response.json()["parcel"]["status"] == "PICKUP_FAILED"
    assert len(get_device().opened) == 1


def test_the_parcel_of_somebody_else_looks_like_one_that_does_not_exist(world):
    parcel = ready_parcel(world, phone=BOB)
    client = client_for(world.alice)
    others = pickup(client, parcel.tracking_code, {"code": parcel.code})
    missing = pickup(client, "0000000000000000", {"code": parcel.code}, key="key-2")
    assert others.status_code == missing.status_code == 404
    assert others.json() == missing.json()
    assert get_device().calls == 0
    assert reload(world, parcel).wrong_code_attempts == 0


@pytest.mark.parametrize("body", [{}, {"code": ""}, {"code": None}])
def test_a_missing_code_is_a_bad_request_and_not_counted(world, body):
    parcel = ready_parcel(world)
    response = pickup(client_for(world.alice), parcel.tracking_code, body)
    assert response.status_code == 400
    assert reload(world, parcel).wrong_code_attempts == 0


def test_the_idempotency_key_is_required(world):
    parcel = ready_parcel(world)
    response = pickup(
        client_for(world.alice), parcel.tracking_code, {"code": parcel.code}, key=None
    )
    assert response.status_code == 400
    assert response.json()["code"] == "idempotency_key_required"
    assert get_device().calls == 0
    assert reload(world, parcel).status == "READY_FOR_PICKUP"


def test_a_key_cannot_be_reused_with_another_code(world):
    parcel = ready_parcel(world)
    client = client_for(world.alice)
    pickup(client, parcel.tracking_code, {"code": wrong(parcel.code)})
    response = pickup(client, parcel.tracking_code, {"code": parcel.code})
    assert response.status_code == 422
    assert response.json()["code"] == "idempotency_key_reused"
    assert reload(world, parcel).wrong_code_attempts == 1
    assert get_device().calls == 0


def test_a_parcel_that_is_not_ready_is_a_conflict(world):
    parcel = new_parcel(world)
    response = pickup(client_for(world.alice), parcel.tracking_code, {"code": "123456"})
    assert response.status_code == 409
    assert response.json()["code"] == "invalid_transition"
    assert get_device().calls == 0


def test_anonymous_callers_are_refused(world):
    parcel = ready_parcel(world)
    response = pickup(APIClient(), parcel.tracking_code, {"code": parcel.code})
    assert response.status_code == 401
    assert get_device().calls == 0


def test_pickup_requests_are_throttled_per_ip(world, monkeypatch):
    monkeypatch.setattr(PickupThrottle, "THROTTLE_RATES", {"pickup": "2/hour"})
    parcel = ready_parcel(world)
    client = client_for(world.alice)
    for index in range(2):
        pickup(client, parcel.tracking_code, {"code": wrong(parcel.code)}, key=f"k{index}")
    response = pickup(client, parcel.tracking_code, {"code": parcel.code}, key="k-last")
    assert response.status_code == 429
    assert reload(world, parcel).wrong_code_attempts == 2
    assert get_device().calls == 0
