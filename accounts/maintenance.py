"""Housekeeping for the accounts app. Plain functions, usable from a command or a task."""

from datetime import timedelta

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from .models import OTPChallenge


class InvalidRetention(ValueError):
    """The retention is so short that deleting would change the OTP rate limit."""


def purge_otp_challenges(*, days, dry_run=False, now=None):
    """Delete closed or expired OTP challenges older than `days`. Returns how many.

    Open challenges that can still be used are never deleted. The per-phone
    hourly cap counts recent challenges, so deleting inside that window would
    silently raise the cap: `days` must be at least 1 and longer than
    OTP_RATE_WINDOW_SECONDS. With `dry_run` nothing is deleted.
    """
    retention = timedelta(days=days)
    if days < 1 or retention.total_seconds() <= settings.OTP_RATE_WINDOW_SECONDS:
        raise InvalidRetention(days)
    now = now or timezone.now()
    stale = OTPChallenge.objects.filter(created_at__lt=now - retention).filter(
        Q(closed_at__isnull=False) | Q(expires_at__lt=now)
    )
    if dry_run:
        return stale.count()
    deleted, _ = stale.delete()
    return deleted
