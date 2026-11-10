from datetime import timedelta

import pytest
from django.db import IntegrityError, connection, transaction
from django.utils import timezone
from django_tenants.utils import tenant_context

from idempotency.models import IdempotencyKey

pytestmark = pytest.mark.django_db(transaction=True)


def schemas_with_table(table):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT table_schema FROM information_schema.tables WHERE table_name = %s",
            [table],
        )
        return {row[0] for row in cursor.fetchall()}


def record(key="k", endpoint="parcel.pickup:1", user_id=1, **extra):
    return IdempotencyKey.objects.create(
        key=key,
        endpoint=endpoint,
        user_id=user_id,
        request_hash="x" * 64,
        expires_at=timezone.now() + timedelta(hours=24),
        **extra,
    )


def test_the_table_exists_only_in_the_tenant_schema(make_org):
    organization = make_org("acme")
    assert schemas_with_table("idempotency_idempotencykey") == {organization.schema_name}


def test_a_new_record_is_still_running(make_org):
    with tenant_context(make_org("acme")):
        created = record()
        assert created.response_status is None
        assert created.response_body is None


def test_a_key_is_unique_per_endpoint_and_user(make_org):
    with tenant_context(make_org("acme")):
        record()
        record(user_id=2)  # another user may use the same key
        record(endpoint="parcel.deposit:1")  # and so may another endpoint
        with pytest.raises(IntegrityError), transaction.atomic():
            record()


@pytest.mark.parametrize("status", [99, 600])
def test_a_response_status_must_be_a_real_http_status(make_org, status):
    with tenant_context(make_org("acme")):
        with pytest.raises(IntegrityError), transaction.atomic():
            record(response_status=status)


@pytest.mark.parametrize("status", [100, 201, 409, 599])
def test_real_http_statuses_are_accepted(make_org, status):
    with tenant_context(make_org("acme")):
        assert record(response_status=status, response_body={"ok": True}).pk


def test_records_are_isolated_between_organizations(make_org):
    org_a, org_b = make_org("acme"), make_org("globex")
    with tenant_context(org_a):
        record()
    with tenant_context(org_b):
        assert IdempotencyKey.objects.count() == 0
        record()  # the same key is free in another organization
    with tenant_context(org_a):
        assert IdempotencyKey.objects.count() == 1
