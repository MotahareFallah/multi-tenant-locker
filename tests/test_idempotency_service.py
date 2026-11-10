from datetime import timedelta

import pytest
from django.db import transaction
from django.utils import timezone
from django_tenants.utils import tenant_context

from idempotency.models import IdempotencyKey
from idempotency.services import (
    IdempotencyKeyReused,
    InvalidIdempotencyKey,
    RequestInProgress,
    execute,
    hash_request,
    purge_expired_keys,
)

pytestmark = pytest.mark.django_db(transaction=True)

ENDPOINT = "parcel.pickup:1"
DATA = {"code": "123456"}


@pytest.fixture
def tenant(make_org):
    organization = make_org("acme")
    with tenant_context(organization):
        yield organization


class Handler:
    def __init__(self, status=201, body=None):
        self.status = status
        self.body = {"ok": True} if body is None else body
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.status, self.body


def run(handler, *, key="k", endpoint=ENDPOINT, user_id=1, data=DATA):
    return execute(
        key=key,
        endpoint=endpoint,
        user_id=user_id,
        request_data=data,
        handler=handler,
    )


def stored_record(data=DATA, hours=1, **extra):
    return IdempotencyKey.objects.create(
        key="k",
        endpoint=ENDPOINT,
        user_id=1,
        request_hash=hash_request(data),
        expires_at=timezone.now() + timedelta(hours=hours),
        **extra,
    )


def test_the_first_request_runs_the_handler_and_stores_the_response(tenant):
    handler = Handler(201, {"id": 7})
    response = run(handler)
    assert (response.status_code, response.body, response.replayed) == (
        201,
        {"id": 7},
        False,
    )
    assert handler.calls == 1
    record = IdempotencyKey.objects.get()
    assert (record.response_status, record.response_body) == (201, {"id": 7})


def test_the_same_request_is_replayed_without_running_the_handler(tenant):
    handler = Handler(201, {"id": 7})
    run(handler)
    again = run(handler)
    assert (again.status_code, again.body, again.replayed) == (201, {"id": 7}, True)
    assert handler.calls == 1


def test_the_order_of_fields_in_the_body_does_not_matter(tenant):
    handler = Handler()
    run(handler, data={"a": 1, "b": 2})
    assert run(handler, data={"b": 2, "a": 1}).replayed
    assert handler.calls == 1


def test_a_refusal_is_stored_and_replayed_too(tenant):
    handler = Handler(409, {"detail": "wrong code"})
    run(handler)
    again = run(handler)
    assert (again.status_code, again.replayed) == (409, True)
    assert handler.calls == 1


def test_the_same_key_with_a_different_body_is_refused(tenant):
    handler = Handler()
    run(handler, data={"code": "111111"})
    with pytest.raises(IdempotencyKeyReused):
        run(handler, data={"code": "222222"})
    assert handler.calls == 1


def test_another_endpoint_or_user_has_its_own_keys(tenant):
    first, other_endpoint, other_user = Handler(), Handler(), Handler()
    run(first)
    run(other_endpoint, endpoint="parcel.deposit:1")
    run(other_user, user_id=2)
    assert (first.calls, other_endpoint.calls, other_user.calls) == (1, 1, 1)


def test_a_request_that_is_still_running_is_reported(tenant):
    stored_record()  # claimed, no response yet
    handler = Handler()
    with pytest.raises(RequestInProgress):
        run(handler)
    assert handler.calls == 0


def test_a_different_body_beats_the_in_progress_answer(tenant):
    stored_record(data={"code": "111111"})
    with pytest.raises(IdempotencyKeyReused):
        run(Handler(), data={"code": "222222"})


def test_an_unexpected_error_releases_the_key(tenant):
    def broken():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        run(broken)
    assert IdempotencyKey.objects.count() == 0
    handler = Handler()
    assert not run(handler).replayed  # the client can simply try again
    assert handler.calls == 1


def test_an_invalid_status_from_the_handler_releases_the_key(tenant):
    with pytest.raises(ValueError):
        run(Handler(status=99))
    assert IdempotencyKey.objects.count() == 0


def test_a_body_that_cannot_be_stored_releases_the_key(tenant):
    with pytest.raises(TypeError):
        run(Handler(body={"x": object()}))
    assert IdempotencyKey.objects.count() == 0


def test_an_expired_record_is_treated_as_a_new_request(tenant):
    stored_record(hours=-1, response_status=200, response_body={"old": True})
    handler = Handler(201, {"new": True})
    response = run(handler)
    assert (response.body, response.replayed) == ({"new": True}, False)
    assert handler.calls == 1
    record = IdempotencyKey.objects.get()
    assert record.response_body == {"new": True}
    assert record.expires_at > timezone.now()


def test_the_record_lives_for_the_configured_time(tenant, settings):
    settings.IDEMPOTENCY_TTL_HOURS = 2
    before = timezone.now()
    run(Handler())
    expires_at = IdempotencyKey.objects.get().expires_at
    assert before + timedelta(hours=2) <= expires_at <= timezone.now() + timedelta(hours=2)


def test_purge_removes_only_expired_records(tenant):
    for key in ("old-1", "old-2"):
        IdempotencyKey.objects.create(
            key=key,
            endpoint=ENDPOINT,
            user_id=1,
            request_hash="x" * 64,
            expires_at=timezone.now() - timedelta(hours=1),
        )
    stored_record(hours=1)
    assert purge_expired_keys() == 2
    assert IdempotencyKey.objects.count() == 1


@pytest.mark.parametrize(
    "key", ["", "a" * 256, "bad\nkey", " padded ", None, 123]
)
def test_invalid_keys_are_refused(tenant, key):
    handler = Handler()
    with pytest.raises(InvalidIdempotencyKey):
        run(handler, key=key)
    assert handler.calls == 0


def test_execute_refuses_to_run_inside_a_transaction(tenant):
    handler = Handler()
    with transaction.atomic(), pytest.raises(RuntimeError):
        run(handler)
    assert handler.calls == 0


def test_keys_are_isolated_between_organizations(make_org):
    org_a, org_b = make_org("acme"), make_org("globex")
    in_a, in_b = Handler(), Handler()
    with tenant_context(org_a):
        run(in_a)
    with tenant_context(org_b):
        assert not run(in_b).replayed  # the same key is new in another organization
    assert (in_a.calls, in_b.calls) == (1, 1)
