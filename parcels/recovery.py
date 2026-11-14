"""Recover pickups that never finished (ADR-0003).

A crash between the door command and recording its result leaves a parcel in
PICKUP_IN_PROGRESS. Nobody knows whether the door opened, so the parcel is moved
to PICKUP_FAILED, the same state a device timeout leads to, and an operator
checks the locker. Plain functions, so the rules can be tested without Celery.
"""

from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from organizations.tenancy import run_in_each_organization

from .models import Parcel, ParcelStatus
from .state_machine import InvalidTransition, transition


def recover_stuck_pickups(*, now=None):
    """Fail the pickups of the current tenant that did not finish. Returns how many.

    A parcel counts as stuck after PICKUP_RECOVERY_MINUTES in PICKUP_IN_PROGRESS
    (`updated_at` is saved by every transition). That must be far longer than any
    device timeout, or a pickup that is still running would be failed under it.
    Safe to run twice: `transition()` locks the row, so a pickup that finished in
    the meantime is skipped.
    """
    now = now or timezone.now()
    cutoff = now - timedelta(minutes=settings.PICKUP_RECOVERY_MINUTES)
    stuck = list(
        Parcel.objects.filter(
            status=ParcelStatus.PICKUP_IN_PROGRESS, updated_at__lt=cutoff
        ).values_list("pk", flat=True)
    )
    recovered = 0
    for parcel_id in stuck:
        try:
            transition(
                parcel_id,
                ParcelStatus.PICKUP_FAILED,
                actor="system",
                reason="pickup did not finish; door state unknown",
            )
        except InvalidTransition:
            continue
        recovered += 1
    return recovered


def recover_all_organizations(*, now=None):
    """Recover stuck pickups in every organization. Returns {slug: count}."""
    return run_in_each_organization(lambda: recover_stuck_pickups(now=now))
