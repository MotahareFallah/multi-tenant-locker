import pytest

from accounts import customer_auth
from accounts.models import User

E164 = "+989123456789"

pytestmark = [pytest.mark.concurrency, pytest.mark.django_db(transaction=True)]


def test_concurrent_user_creation_yields_exactly_one_user(run_concurrently):
    results = run_concurrently(lambda: customer_auth.get_or_create_user(E164).pk, 8)
    assert all(error is None for _, error in results)
    assert len({pk for pk, _ in results}) == 1
    assert User.objects.count() == 1
