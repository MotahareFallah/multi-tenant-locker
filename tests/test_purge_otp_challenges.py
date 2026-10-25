from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from accounts.models import OTPChallenge, OTPCloseReason, OTPPurpose

pytestmark = pytest.mark.django_db


def make_challenge(phone, *, age_days, closed, expired=True):
    now = timezone.now()
    challenge = OTPChallenge.objects.create(
        phone_number=phone,
        purpose=OTPPurpose.CUSTOMER_SIGN_IN,
        code_hash="0" * 64,
        expires_at=now - timedelta(days=age_days) + timedelta(minutes=2)
        if expired
        else now + timedelta(minutes=2),
        closed_at=now if closed else None,
        closed_reason=OTPCloseReason.CONSUMED if closed else "",
    )
    OTPChallenge.objects.filter(pk=challenge.pk).update(
        created_at=now - timedelta(days=age_days)
    )
    return challenge


def run(*args):
    out = StringIO()
    call_command("purge_otp_challenges", *args, stdout=out)
    return out.getvalue()


def test_old_closed_challenges_are_deleted_and_recent_ones_kept():
    old = make_challenge("+989120000001", age_days=40, closed=True)
    recent = make_challenge("+989120000002", age_days=5, closed=True)
    assert "Deleted 1" in run("--days", "30")
    assert not OTPChallenge.objects.filter(pk=old.pk).exists()
    assert OTPChallenge.objects.filter(pk=recent.pk).exists()


def test_old_expired_but_unclosed_challenges_are_deleted():
    stale = make_challenge("+989120000003", age_days=40, closed=False)
    run("--days", "30")
    assert not OTPChallenge.objects.filter(pk=stale.pk).exists()


def test_a_challenge_that_can_still_be_used_is_never_deleted():
    live = make_challenge("+989120000004", age_days=40, closed=False, expired=False)
    run("--days", "30")
    assert OTPChallenge.objects.filter(pk=live.pk).exists()


def test_dry_run_reports_but_deletes_nothing():
    make_challenge("+989120000005", age_days=40, closed=True)
    assert "Would delete 1" in run("--days", "30", "--dry-run")
    assert OTPChallenge.objects.count() == 1


@pytest.mark.parametrize("days", ["0", "-5"])
def test_a_retention_below_one_day_is_rejected(days):
    with pytest.raises(CommandError):
        run("--days", days)


def test_a_retention_shorter_than_the_rate_window_is_rejected(settings):
    settings.OTP_RATE_WINDOW_SECONDS = 3 * 24 * 3600
    with pytest.raises(CommandError):
        run("--days", "2")
