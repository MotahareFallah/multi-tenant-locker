from celery import shared_task

from .expiry import expire_all_organizations
from .recovery import recover_all_organizations


@shared_task(name="parcels.expire_overdue")
def expire_overdue_parcels_task():
    """Run by Celery beat. Returns {organization slug: parcels expired}."""
    return expire_all_organizations()


@shared_task(name="parcels.recover_stuck_pickups")
def recover_stuck_pickups_task():
    """Run by Celery beat. Returns {organization slug: pickups recovered}."""
    return recover_all_organizations()
