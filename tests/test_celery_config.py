from django.conf import settings

from config import celery_app


def test_the_app_reads_its_broker_from_settings():
    assert celery_app.conf.broker_url == settings.CELERY_BROKER_URL


def test_task_results_are_not_stored():
    assert celery_app.conf.task_ignore_result is True
