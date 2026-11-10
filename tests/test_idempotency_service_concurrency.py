import itertools
import time

import pytest
from django_tenants.utils import tenant_context

from idempotency.services import IdempotencyKeyReused, RequestInProgress, execute

pytestmark = pytest.mark.django_db(transaction=True)


def test_concurrent_copies_of_one_request_run_the_handler_once(
    make_org, run_concurrently
):
    organization = make_org("acme")
    calls = []

    def slow_handler():
        calls.append(1)
        time.sleep(0.3)  # keep the first request running while the others arrive
        return 201, {"ok": True}

    def send():
        with tenant_context(organization):
            return execute(
                key="k",
                endpoint="parcel.pickup:1",
                user_id=1,
                request_data={"code": "123456"},
                handler=slow_handler,
            )

    outcomes = run_concurrently(send, 8)
    assert len(calls) == 1
    first_runs = [r for r, e in outcomes if e is None and not r.replayed]
    assert len(first_runs) == 1
    for _result, error in outcomes:
        assert error is None or isinstance(error, RequestInProgress)
    with tenant_context(organization):
        later = send()
    assert (later.status_code, later.replayed) == (201, True)
    assert len(calls) == 1


def test_concurrent_requests_with_different_bodies_run_once(make_org, run_concurrently):
    organization = make_org("acme")
    counter = itertools.count()
    calls = []

    def handler():
        calls.append(1)
        time.sleep(0.2)
        return 201, {"ok": True}

    def send():
        with tenant_context(organization):
            return execute(
                key="k",
                endpoint="parcel.pickup:1",
                user_id=1,
                request_data={"code": str(next(counter))},
                handler=handler,
            )

    outcomes = run_concurrently(send, 8)
    successes = [r for r, e in outcomes if e is None]
    errors = [e for r, e in outcomes if e is not None]
    assert len(calls) == 1
    assert len(successes) == 1
    assert len(errors) == 7
    assert all(isinstance(error, IdempotencyKeyReused) for error in errors)
