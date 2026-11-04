import itertools
import threading

import pytest
from django.contrib.auth import get_user_model

from organizations.models import Membership, Organization, Role
from organizations.services import LastAdminError, add_member, deactivate_member

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.concurrency]


def deactivate_each_other(run_concurrently, first, second):
    """Two threads start together; each deactivates the other admin."""
    targets = [second, first]
    counter = itertools.count()
    lock = threading.Lock()

    def worker():
        with lock:
            target = targets[next(counter)]
        return deactivate_member(target)

    return run_concurrently(worker, 2)


def test_two_admins_cannot_remove_each_other_at_the_same_time(run_concurrently):
    org = Organization(name="acme", slug="acme", schema_name="org_acme")
    org.auto_create_schema = False
    org.save()
    users = [
        get_user_model().objects.create(phone_number=f"+98912000{n:04d}")
        for n in (1, 2)
    ]
    first, second = (
        add_member(organization=org, user=user, role=Role.ADMIN) for user in users
    )

    for _ in range(5):
        Membership.objects.filter(organization=org).update(
            is_active=True, role=Role.ADMIN
        )
        results = deactivate_each_other(run_concurrently, first, second)
        errors = [error for _, error in results if error is not None]
        assert len(errors) == 1
        assert isinstance(errors[0], LastAdminError)
        active_admins = Membership.objects.filter(
            organization=org, role=Role.ADMIN, is_active=True
        )
        assert active_admins.count() == 1
