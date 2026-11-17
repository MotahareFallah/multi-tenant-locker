import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from organizations.models import Membership, Role
from organizations.services import add_member
from tests.helpers import client_for, make_org_row

pytestmark = pytest.mark.django_db


def make_user(number):
    return get_user_model().objects.create(phone_number=f"+98912000{number:04d}")


def get(client, slug):
    return client.get(f"/api/v1/orgs/{slug}/")


def test_a_member_sees_the_organization_and_their_role():
    user = make_user(1)
    add_member(organization=make_org_row("acme", "Acme Inc"), user=user, role=Role.OPERATOR)
    response = get(client_for(user), "acme")
    assert response.status_code == 200
    assert response.json() == {"slug": "acme", "name": "Acme Inc", "role": "operator"}


def test_a_real_access_token_works():
    user = make_user(1)
    add_member(organization=make_org_row("acme"), user=user, role=Role.ADMIN)
    token = str(RefreshToken.for_user(user).access_token)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    assert get(client, "acme").status_code == 200


def test_an_unknown_slug_is_a_404():
    assert get(client_for(make_user(1)), "missing").status_code == 404


def test_a_non_member_gets_a_404():
    add_member(organization=make_org_row("acme"), user=make_user(1), role=Role.ADMIN)
    assert get(client_for(make_user(2)), "acme").status_code == 404


def test_an_inactive_membership_gets_a_404():
    user = make_user(1)
    membership = add_member(organization=make_org_row("acme"), user=user, role=Role.ADMIN)
    Membership.objects.filter(pk=membership.pk).update(is_active=False)
    assert get(client_for(user), "acme").status_code == 404


def test_the_three_404_cases_are_indistinguishable():
    owner, outsider = make_user(1), make_user(2)
    organization = make_org_row("acme")
    add_member(organization=organization, user=owner, role=Role.ADMIN)
    inactive = add_member(organization=make_org_row("globex"), user=outsider, role=Role.ADMIN)
    Membership.objects.filter(pk=inactive.pk).update(is_active=False)

    responses = [
        get(client_for(outsider), "missing"),  # unknown slug
        get(client_for(outsider), "acme"),  # somebody else's organization
        get(client_for(outsider), "globex"),  # inactive membership
    ]
    assert {r.status_code for r in responses} == {404}
    assert len({r.content for r in responses}) == 1


def test_an_anonymous_request_gets_a_401():
    make_org_row("acme")
    assert get(APIClient(), "acme").status_code == 401


def test_an_invalid_token_gets_a_401():
    make_org_row("acme")
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Bearer not-a-token")
    assert get(client, "acme").status_code == 401


def test_the_schema_is_public_after_a_successful_request():
    user = make_user(1)
    add_member(organization=make_org_row("acme"), user=user, role=Role.ADMIN)
    assert get(client_for(user), "acme").status_code == 200
    assert connection.schema_name == "public"


def test_the_schema_is_public_after_a_rejected_request():
    user = make_user(1)
    make_org_row("acme")
    assert get(client_for(user), "acme").status_code == 404
    assert connection.schema_name == "public"


def test_the_schema_is_public_after_an_unauthenticated_request():
    make_org_row("acme")
    assert get(APIClient(), "acme").status_code == 401
    assert connection.schema_name == "public"
