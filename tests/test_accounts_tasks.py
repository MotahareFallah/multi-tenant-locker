from datetime import timedelta

import pytest
from django.conf import settings
from django.utils import timezone

from accounts.maintenance import InvalidRetention, purge_otp_challenges
from accounts.models import OTPChallenge, OTPCloseReason, OTPPurpose
from accounts.tasks import purge_otp_challenges_task
from config import celery_app

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


def exists(challenge):
    return OTPChallenge.objects.filter(pk=challenge.pk).exists()


def test_the_task_deletes_old_closed_challenges_and_keeps_recent_ones():
    old = make_challenge("+989120000001", age_days=40, closed=True)
    recent = make_challenge("+989120000002", age_days=5, closed=True)
    assert purge_otp_challenges_task.apply().get() == 1
    assert not exists(old)
    assert exists(recent)


def test_the_task_uses_the_configured_retention(settings):
    challenge = make_challenge("+989120000003", age_days=5, closed=True)
    settings.OTP_CHALLENGE_RETENTION_DAYS = 3
    assert purge_otp_challenges_task.apply().get() == 1
    assert not exists(challenge)


def test_an_old_challenge_that_can_still_be_used_is_never_deleted():
    open_one = make_challenge("+989120000004", age_days=40, closed=False, expired=False)
    assert purge_otp_challenges_task.apply().get() == 0
    assert exists(open_one)


def test_a_retention_that_would_raise_the_rate_limit_fails_the_task(settings):
    challenge = make_challenge("+989120000005", age_days=40, closed=True)
    settings.OTP_CHALLENGE_RETENTION_DAYS = 0
    result = purge_otp_challenges_task.apply()
    with pytest.raises(InvalidRetention):
        result.get()
    assert exists(challenge)


def test_a_retention_inside_the_rate_window_is_refused(settings):
    settings.OTP_RATE_WINDOW_SECONDS = 2 * 24 * 3600
    with pytest.raises(InvalidRetention):
        purge_otp_challenges(days=1)


def test_a_dry_run_counts_without_deleting():
    old = make_challenge("+989120000006", age_days=40, closed=True)
    assert purge_otp_challenges(days=30, dry_run=True) == 1
    assert exists(old)


def test_the_beat_schedule_points_at_the_registered_task():
    entry = settings.CELERY_BEAT_SCHEDULE["purge-otp-challenges"]
    assert entry["task"] == purge_otp_challenges_task.name
    assert entry["task"] in celery_app.tasks
    assert entry["schedule"] > 0
