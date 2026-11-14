from celery import shared_task

from organizations.tenancy import run_in_each_organization

from .services import purge_expired_keys


@shared_task(name="idempotency.purge_expired_keys")
def purge_expired_keys_task():
    """Run by Celery beat. Returns {organization slug: keys deleted}.

    The keys live in each organization's schema, so every one is visited.
    """
    return run_in_each_organization(purge_expired_keys)
