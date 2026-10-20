import pytest
from django.db import connection


@pytest.mark.django_db
def test_database_connection():
    with connection.cursor() as cursor:
        cursor.execute("select 1")
        assert cursor.fetchone() == (1,)
