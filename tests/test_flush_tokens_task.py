from datetime import timedelta

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.tasks import flush_expired_tokens_task
from config import celery_app

pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    return get_user_model().objects.create(phone_number="+989120000010")


def expire(token):
    OutstandingToken.objects.filter(jti=token["jti"]).update(
        expires_at=timezone.now() - timedelta(days=1)
    )


def stored(token):
    return OutstandingToken.objects.filter(jti=token["jti"]).exists()


def test_an_expired_token_is_deleted_and_a_live_one_is_kept(user):
    old = RefreshToken.for_user(user)
    live = RefreshToken.for_user(user)
    expire(old)
    flush_expired_tokens_task.apply().get()
    assert not stored(old)
    assert stored(live)


def test_a_blacklisted_token_goes_with_its_expired_record(user):
    token = RefreshToken.for_user(user)
    token.blacklist()
    assert BlacklistedToken.objects.count() == 1
    expire(token)
    flush_expired_tokens_task.apply().get()
    assert not stored(token)
    assert BlacklistedToken.objects.count() == 0


def test_a_blacklisted_token_that_has_not_expired_stays_blacklisted(user):
    token = RefreshToken.for_user(user)
    token.blacklist()
    flush_expired_tokens_task.apply().get()
    assert BlacklistedToken.objects.count() == 1


def test_the_beat_schedule_points_at_the_registered_task():
    entry = settings.CELERY_BEAT_SCHEDULE["flush-expired-tokens"]
    assert entry["task"] == flush_expired_tokens_task.name
    assert entry["task"] in celery_app.tasks
    assert entry["schedule"] > 0
