"""Run a job once for every organization, each in its own schema."""

import logging

from django_tenants.utils import get_public_schema_name, tenant_context

from .models import Organization

logger = logging.getLogger(__name__)


class OrganizationJobsFailed(Exception):
    """The job failed in at least one organization, after every one was tried.

    `results` holds {slug: result} of the organizations that worked and `failed`
    the slugs of the ones that did not.
    """

    def __init__(self, results, failed):
        # `args` must be the constructor arguments, or the exception cannot be
        # pickled and Celery would replace it with an opaque wrapper.
        super().__init__(results, failed)
        self.results = results
        self.failed = failed

    def __str__(self):
        return "Job failed for organization(s): " + ", ".join(self.failed)


def run_in_each_organization(job):
    """Call `job()` inside every organization's schema. Returns {slug: result}.

    A failure is logged and does not stop the others. After all of them were
    tried, `OrganizationJobsFailed` is raised if any failed, so a Celery task that
    uses this ends as FAILED and the problem is visible, not only in the log.
    Outside Celery there is no implicit tenant (ADR-0002), so the schema is always
    set explicitly here.
    """
    results = {}
    failed = []
    organizations = Organization.objects.exclude(
        schema_name=get_public_schema_name()
    ).order_by("pk")
    for organization in organizations:
        try:
            with tenant_context(organization):
                results[organization.slug] = job()
        except Exception:
            logger.exception("Job failed for organization %s", organization.slug)
            failed.append(organization.slug)
    if failed:
        raise OrganizationJobsFailed(results, failed)
    return results
