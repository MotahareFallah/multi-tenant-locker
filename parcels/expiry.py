"""Expire parcels whose storage period has ended (ADR-0003).

Plain functions, so the rules can be tested without Celery. The task in
tasks.py only calls `expire_all_organizations`.
"""

import logging

from django.utils import timezone
from django_tenants.utils import get_public_schema_name, tenant_context

from organizations.models import Organization

from .models import Parcel, ParcelStatus
from .state_machine import InvalidTransition, transition

logger = logging.getLogger(__name__)

# PICKUP_IN_PROGRESS is left alone: the pickup finishes or fails first.
EXPIRABLE_STATUSES = [
    ParcelStatus.CREATED,
    ParcelStatus.STORED,
    ParcelStatus.READY_FOR_PICKUP,
    ParcelStatus.PICKUP_FAILED,
]


def expire_overdue_parcels(*, now=None):
    """Expire the overdue parcels of the current tenant. Returns how many.

    Safe to run twice and safe to race with a pickup: `transition()` locks the
    row, and whoever gets the lock first wins. A parcel that changed state after
    it was selected is skipped.
    """
    now = now or timezone.now()
    overdue = list(
        Parcel.objects.filter(
            status__in=EXPIRABLE_STATUSES, expires_at__lt=now
        ).values_list("pk", flat=True)
    )
    expired = 0
    for parcel_id in overdue:
        try:
            transition(
                parcel_id,
                ParcelStatus.EXPIRED,
                actor="system",
                reason="storage period ended",
            )
        except InvalidTransition:
            continue
        expired += 1
    return expired


def expire_all_organizations(*, now=None):
    """Expire overdue parcels in every organization. Returns {slug: count}.

    An organization that fails is logged and skipped; it must not stop the rest.
    """
    results = {}
    organizations = Organization.objects.exclude(
        schema_name=get_public_schema_name()
    ).order_by("pk")
    for organization in organizations:
        try:
            with tenant_context(organization):
                results[organization.slug] = expire_overdue_parcels(now=now)
        except Exception:
            logger.exception("Expiring parcels failed for %s", organization.slug)
    return results
