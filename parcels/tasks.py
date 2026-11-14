from celery import shared_task

from .expiry import expire_all_organizations


@shared_task(name="parcels.expire_overdue")
def expire_overdue_parcels_task():
    """Run by Celery beat. Returns {organization slug: parcels expired}."""
    return expire_all_organizations()
