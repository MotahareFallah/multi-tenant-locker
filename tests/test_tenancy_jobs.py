import pickle

import pytest
from django.db import connection

from organizations.tenancy import OrganizationJobsFailed, run_in_each_organization

pytestmark = pytest.mark.django_db(transaction=True)


def test_the_job_runs_in_the_schema_of_each_organization(make_org):
    acme = make_org("acme")
    globex = make_org("globex")
    results = run_in_each_organization(lambda: connection.schema_name)
    assert results == {"acme": acme.schema_name, "globex": globex.schema_name}
    assert connection.schema_name == "public"


def test_without_organizations_nothing_runs():
    assert run_in_each_organization(lambda: 1 / 0) == {}


def test_a_failing_organization_is_reported_after_the_others_ran(make_org):
    make_org("acme")
    make_org("globex")

    def job():
        if connection.tenant.slug == "acme":
            raise RuntimeError("boom")
        return "done"

    with pytest.raises(OrganizationJobsFailed) as caught:
        run_in_each_organization(job)
    assert caught.value.results == {"globex": "done"}
    assert caught.value.failed == ["acme"]
    assert "acme" in str(caught.value)
    assert connection.schema_name == "public"


def test_the_exception_survives_pickling():
    # Celery pickles a task's exception; a wrapper would hide what failed.
    error = OrganizationJobsFailed({"globex": 1}, ["acme"])
    copy = pickle.loads(pickle.dumps(error))
    assert isinstance(copy, OrganizationJobsFailed)
    assert copy.results == {"globex": 1}
    assert copy.failed == ["acme"]
    assert str(copy) == str(error)
