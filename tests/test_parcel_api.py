import json
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django_tenants.utils import tenant_context
from rest_framework.test import APIClient

from accounts import sms
from idempotency.models import IdempotencyKey
from lockers.models import Compartment, CompartmentSize, Locker
from organizations.models import Role
from organizations.services import add_member
from parcels.models import Parcel
from parcels.pickup_code import pickup_code_matches
from parcels.services import create_parcel, deposit_parcel
from parcels.state_machine import MAX_PICKUP_ATTEMPTS

pytestmark = pytest.mark.django_db(transaction=True)

BASE = "/api/v1/orgs/acme/"
NEW = {"locker": "main", "recipient_phone": "09351234567", "size": "SMALL"}
SEED_PHONE_E164 = "+989123456789"

ENDPOINTS = [
    ("get", "parcels/"),
    ("post", "parcels/"),
    ("get", "parcels/{tc}/"),
    ("post", "parcels/{tc}/deposit/"),
    ("post", "parcels/{tc}/pickup-code/"),
]


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def post(client, path, data=None, key="key-1"):
    extra = {} if key is None else {"HTTP_IDEMPOTENCY_KEY": key}
    return client.post(BASE + path, data or {}, format="json", **extra)


def get(client, path):
    return client.get(BASE + path)


def replayed(response):
    return response.headers.get("Idempotent-Replayed") == "true"


def code_in(message):
    return message.rsplit(" ", 1)[-1]


@pytest.fixture
def staff(make_org):
    users = get_user_model().objects
    organization = make_org("acme")
    admin = users.create(phone_number="+989120000001")
    operator = users.create(phone_number="+989120000002")
    outsider = users.create(phone_number="+989120000003")
    add_member(organization=organization, user=admin, role=Role.ADMIN)
    add_member(organization=organization, user=operator, role=Role.OPERATOR)
    with tenant_context(organization):
        locker = Locker.objects.create(code="main", name="Main hall")
        Compartment.objects.create(locker=locker, number=1, size=CompartmentSize.SMALL)
        parcel = create_parcel(
            locker=locker,
            recipient_phone="09123456789",
            size=CompartmentSize.SMALL,
            actor="seed",
        )
    return SimpleNamespace(
        org=organization,
        operator_user=operator,
        admin=client_for(admin),
        operator=client_for(operator),
        outsider=client_for(outsider),
        anonymous=APIClient(),
        tracking_code=parcel.tracking_code,
    )


def deposited(staff):
    with tenant_context(staff.org):
        parcel = Parcel.objects.get(tracking_code=staff.tracking_code)
        deposit_parcel(parcel.pk, actor="seed")
    return staff.tracking_code


# Who may call what


@pytest.mark.parametrize("method, path", ENDPOINTS)
def test_anonymous_callers_are_refused(staff, method, path):
    url = path.format(tc=staff.tracking_code)
    assert post(staff.anonymous, url).status_code == 401 if method == "post" else (
        get(staff.anonymous, url).status_code == 401
    )


@pytest.mark.parametrize("method, path", ENDPOINTS)
def test_non_members_see_a_404(staff, method, path):
    url = path.format(tc=staff.tracking_code)
    response = (
        post(staff.outsider, url) if method == "post" else get(staff.outsider, url)
    )
    assert response.status_code == 404


@pytest.mark.parametrize("role", ["admin", "operator"])
def test_admins_and_operators_can_list_parcels(staff, role):
    assert get(getattr(staff, role), "parcels/").status_code == 200


# Creating parcels


def test_an_operator_creates_a_parcel(staff):
    response = post(staff.operator, "parcels/", NEW)
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "CREATED"
    assert body["locker"] == "main"
    assert body["compartment"] is None
    assert body["recipient_phone"] == "+989351234567"
    assert len(body["tracking_code"]) == 16
    assert "pickup_code_hash" not in body


def test_the_calling_user_is_recorded_as_the_actor(staff):
    tracking_code = post(staff.operator, "parcels/", NEW).json()["tracking_code"]
    with tenant_context(staff.org):
        event = Parcel.objects.get(tracking_code=tracking_code).events.get()
    assert event.actor == f"user:{staff.operator_user.pk}"


def test_creating_needs_an_idempotency_key(staff):
    response = post(staff.operator, "parcels/", NEW, key=None)
    assert response.status_code == 400
    assert response.json()["code"] == "idempotency_key_required"
    with tenant_context(staff.org):
        assert Parcel.objects.count() == 1


def test_a_malformed_idempotency_key_is_refused(staff):
    response = post(staff.operator, "parcels/", NEW, key=" padded ")
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_idempotency_key"


@pytest.mark.parametrize(
    "data",
    [
        {**NEW, "locker": "nope"},
        {**NEW, "recipient_phone": "123"},
        {**NEW, "size": "HUGE"},
    ],
)
def test_invalid_parcels_are_rejected(staff, data):
    assert post(staff.operator, "parcels/", data).status_code == 400


def test_an_invalid_request_does_not_use_up_its_key(staff):
    assert post(staff.operator, "parcels/", {**NEW, "size": "HUGE"}, key="k").status_code == 400
    assert post(staff.operator, "parcels/", NEW, key="k").status_code == 201


def test_a_repeated_create_returns_the_same_parcel(staff):
    first = post(staff.operator, "parcels/", NEW, key="k")
    second = post(staff.operator, "parcels/", NEW, key="k")
    assert second.status_code == 201
    assert second.json() == first.json()
    assert replayed(second) and not replayed(first)
    with tenant_context(staff.org):
        assert Parcel.objects.count() == 2  # the seed parcel and one new one


def test_the_same_key_with_another_body_is_refused(staff):
    post(staff.operator, "parcels/", NEW, key="k")
    other = post(staff.operator, "parcels/", {**NEW, "size": "LARGE"}, key="k")
    assert other.status_code == 422
    assert other.json()["code"] == "idempotency_key_reused"


def test_a_switched_off_locker_refuses_new_parcels(staff):
    with tenant_context(staff.org):
        Locker.objects.filter(code="main").update(is_active=False)
    first = post(staff.operator, "parcels/", NEW, key="k")
    assert first.status_code == 409
    assert first.json()["code"] == "locker_unavailable"
    again = post(staff.operator, "parcels/", NEW, key="k")
    assert again.json() == first.json() and replayed(again)


# Listing and reading


def test_the_list_is_newest_first(staff):
    with tenant_context(staff.org):
        locker = Locker.objects.get(code="main")
        created = [
            create_parcel(
                locker=locker,
                recipient_phone="09123456789",
                size=CompartmentSize.SMALL,
                actor="seed",
            ).tracking_code
            for _ in range(3)
        ]
    listed = get(staff.operator, "parcels/").json()["results"]
    assert [item["tracking_code"] for item in listed] == [
        *reversed(created),
        staff.tracking_code,
    ]


def test_the_list_is_paginated(staff):
    with tenant_context(staff.org):
        locker = Locker.objects.get(code="main")
        Parcel.objects.bulk_create(
            [
                Parcel(
                    locker=locker,
                    recipient_phone=SEED_PHONE_E164,
                    size=CompartmentSize.SMALL,
                )
                for _ in range(51)
            ]
        )
    first = get(staff.operator, "parcels/").json()
    assert first["count"] == 52
    assert len(first["results"]) == 50
    second = staff.operator.get(first["next"]).json()
    assert len(second["results"]) == 2


def test_the_list_can_be_filtered_by_status(staff):
    stored = deposited(staff)
    only_stored = get(staff.operator, "parcels/?status=STORED").json()["results"]
    assert [item["tracking_code"] for item in only_stored] == [stored]
    assert get(staff.operator, "parcels/?status=CREATED").json()["count"] == 0
    assert get(staff.operator, "parcels/?status=LOST").status_code == 400


def test_a_parcel_shows_its_history_and_no_secrets(staff):
    response = get(staff.operator, f"parcels/{staff.tracking_code}/")
    assert response.status_code == 200
    body = response.json()
    assert body["events"][0]["to_status"] == "CREATED"
    assert "pickup_code_hash" not in body
    assert body["wrong_code_attempts"] == 0


def test_an_unknown_parcel_is_a_404(staff):
    assert get(staff.operator, "parcels/0000000000000000/").status_code == 404


# Depositing


def test_a_parcel_is_deposited_into_a_compartment(staff):
    response = post(staff.operator, f"parcels/{staff.tracking_code}/deposit/")
    assert response.status_code == 200
    assert (response.json()["status"], response.json()["compartment"]) == ("STORED", 1)


def test_a_repeated_deposit_is_replayed_not_repeated(staff):
    path = f"parcels/{staff.tracking_code}/deposit/"
    first = post(staff.operator, path, key="k")
    second = post(staff.operator, path, key="k")
    assert second.status_code == 200
    assert second.json() == first.json() and replayed(second)


def test_depositing_again_with_a_new_key_is_a_conflict(staff):
    path = f"parcels/{staff.tracking_code}/deposit/"
    post(staff.operator, path, key="k1")
    again = post(staff.operator, path, key="k2")
    assert again.status_code == 409
    assert again.json()["code"] == "invalid_transition"


def test_depositing_needs_a_free_compartment(staff):
    with tenant_context(staff.org):
        Compartment.objects.update(is_active=False)
    response = post(staff.operator, f"parcels/{staff.tracking_code}/deposit/")
    assert response.status_code == 409
    assert response.json()["code"] == "no_free_compartment"
    body = get(staff.operator, f"parcels/{staff.tracking_code}/").json()
    assert body["status"] == "CREATED"


def test_depositing_needs_an_idempotency_key(staff):
    response = post(staff.operator, f"parcels/{staff.tracking_code}/deposit/", key=None)
    assert response.status_code == 400
    assert response.json()["code"] == "idempotency_key_required"


# Sending the pickup code


def test_the_pickup_code_is_texted_and_never_returned(staff, sms_outbox):
    tracking_code = deposited(staff)
    response = post(staff.operator, f"parcels/{tracking_code}/pickup-code/")
    assert response.status_code == 200
    assert response.json()["status"] == "READY_FOR_PICKUP"
    assert len(sms_outbox) == 1
    phone, message = sms_outbox[0]
    assert phone == SEED_PHONE_E164
    code = code_in(message)
    assert code not in response.text
    with tenant_context(staff.org):
        for row in IdempotencyKey.objects.all():
            assert code not in json.dumps(row.response_body)
        parcel = Parcel.objects.get(tracking_code=tracking_code)
        assert pickup_code_matches(parcel, code)


def test_a_repeated_request_does_not_text_again(staff, sms_outbox):
    path = f"parcels/{deposited(staff)}/pickup-code/"
    first = post(staff.operator, path, key="k")
    second = post(staff.operator, path, key="k")
    assert second.json() == first.json() and replayed(second)
    assert len(sms_outbox) == 1


def test_a_new_key_sends_a_fresh_code_and_clears_the_wrong_code_count(staff, sms_outbox):
    tracking_code = deposited(staff)
    path = f"parcels/{tracking_code}/pickup-code/"
    post(staff.operator, path, key="k1")
    with tenant_context(staff.org):
        Parcel.objects.filter(tracking_code=tracking_code).update(wrong_code_attempts=3)
    response = post(staff.operator, path, key="k2")
    assert response.status_code == 200
    assert response.json()["wrong_code_attempts"] == 0
    assert len(sms_outbox) == 2
    with tenant_context(staff.org):
        parcel = Parcel.objects.get(tracking_code=tracking_code)
        assert pickup_code_matches(parcel, code_in(sms_outbox[1][1]))


def test_a_failed_sms_gives_502_and_frees_the_key(staff, monkeypatch):
    class FailingBackend(sms.SmsBackend):
        def send(self, phone_number, message):
            raise sms.SmsDeliveryError("provider is down")

    delivered = []

    class RecordingBackend(sms.SmsBackend):
        def send(self, phone_number, message):
            delivered.append(message)

    path = f"parcels/{deposited(staff)}/pickup-code/"
    monkeypatch.setattr(sms, "get_sms_backend", lambda: FailingBackend())
    failed = post(staff.operator, path, key="k")
    assert failed.status_code == 502
    assert failed.json()["code"] == "sms_delivery_failed"
    with tenant_context(staff.org):
        assert IdempotencyKey.objects.count() == 0

    monkeypatch.setattr(sms, "get_sms_backend", lambda: RecordingBackend())
    retried = post(staff.operator, path, key="k")  # the very same request
    assert retried.status_code == 200
    assert len(delivered) == 1


def test_a_parcel_that_was_not_deposited_gets_no_code(staff, sms_outbox):
    response = post(staff.operator, f"parcels/{staff.tracking_code}/pickup-code/")
    assert response.status_code == 409
    assert response.json()["code"] == "invalid_transition"
    assert sms_outbox == []


def test_no_code_is_sent_once_retries_are_exhausted(staff, sms_outbox):
    tracking_code = deposited(staff)
    with tenant_context(staff.org):
        Parcel.objects.filter(tracking_code=tracking_code).update(
            status="PICKUP_FAILED", pickup_attempts=MAX_PICKUP_ATTEMPTS
        )
    response = post(staff.operator, f"parcels/{tracking_code}/pickup-code/")
    assert response.status_code == 409
    assert response.json()["code"] == "pickup_attempts_exhausted"
    assert sms_outbox == []


# Isolation


def test_parcels_are_isolated_between_organizations(staff, make_org):
    other = make_org("globex")
    with tenant_context(other):
        locker = Locker.objects.create(code="main", name="Other main")
        secret = create_parcel(
            locker=locker,
            recipient_phone="09123456789",
            size=CompartmentSize.SMALL,
            actor="seed",
        ).tracking_code
    listed = get(staff.operator, "parcels/").json()["results"]
    assert [item["tracking_code"] for item in listed] == [staff.tracking_code]
    assert get(staff.operator, f"parcels/{secret}/").status_code == 404
    assert post(staff.operator, f"parcels/{secret}/deposit/").status_code == 404
    assert staff.operator.get("/api/v1/orgs/globex/parcels/").status_code == 404
