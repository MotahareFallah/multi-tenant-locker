"""Run a job once for every organization, each in its own schema."""

import logging

from django_tenants.utils import get_public_schema_name, tenant_context

from .models import Organization

logger = logging.getLogger(__name__)


def run_in_each_organization(job):
    """Call `job()` inside every organization's schema. Returns {slug: result}.

    An organization whose job fails is logged and left out of the result; it
    must not stop the others. Outside Celery there is no implicit tenant
    (ADR-0002), so the schema is always set explicitly here.
    """
    results = {}
    organizations = Organization.objects.exclude(
        schema_name=get_public_schema_name()
    ).order_by("pk")
    for organization in organizations:
        try:
            with tenant_context(organization):
                results[organization.slug] = job()
        except Exception:
            logger.exception("Job failed for organization %s", organization.slug)
    return results
