from rest_framework.test import APIClient

from organizations.models import Organization


def make_org_row(slug, name=None):
    # Only the row, no schema: for tests about access and rules, not about tenancy.
    organization = Organization(
        name=name or slug, slug=slug, schema_name=f"org_{slug.replace('-', '')}"
    )
    organization.auto_create_schema = False
    organization.save()
    return organization


def client_for(user, **kwargs):
    client = APIClient(**kwargs)
    client.force_authenticate(user)
    return client
