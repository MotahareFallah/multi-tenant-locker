from celery import shared_task
from django.conf import settings

from .maintenance import purge_otp_challenges


@shared_task(name="accounts.purge_otp_challenges")
def purge_otp_challenges_task():
    """Run by Celery beat. Returns how many challenges were deleted.

    Raises InvalidRetention if OTP_CHALLENGE_RETENTION_DAYS is too short: a loud
    failure is better than quietly raising the OTP rate limit.
    """
    return purge_otp_challenges(days=settings.OTP_CHALLENGE_RETENTION_DAYS)
