import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from accounts.phone import normalize_phone_number

User = get_user_model()


@pytest.mark.parametrize("raw", ["09123456789", "+98 912 345 6789", "+989123456789"])
def test_normalize_phone_number_to_e164(raw):
    assert normalize_phone_number(raw) == "+989123456789"


@pytest.mark.parametrize("raw", ["", "abc", "12345", "02188776655"])
def test_normalize_phone_number_rejects_invalid_or_non_mobile(raw):
    with pytest.raises(ValidationError):
        normalize_phone_number(raw)


@pytest.mark.django_db
def test_create_user_normalizes_phone_and_has_no_usable_password():
    user = User.objects.create_user(phone_number="09123456789")
    assert user.phone_number == "+989123456789"
    assert not user.has_usable_password()
    assert not user.is_staff
    assert not user.is_superuser


@pytest.mark.django_db
def test_create_user_requires_phone_number():
    with pytest.raises(ValueError):
        User.objects.create_user(phone_number="")


@pytest.mark.django_db
def test_create_user_rejects_invalid_phone_number():
    with pytest.raises(ValidationError):
        User.objects.create_user(phone_number="12345")


@pytest.mark.django_db
def test_create_superuser_requires_password_and_sets_flags():
    with pytest.raises(ValueError):
        User.objects.create_superuser(phone_number="09123456789")
    admin = User.objects.create_superuser(
        phone_number="09123456789", password="s3cret-pass"
    )
    assert admin.is_staff
    assert admin.is_superuser
    assert admin.check_password("s3cret-pass")


@pytest.mark.django_db
def test_same_number_in_different_formats_is_a_duplicate():
    User.objects.create_user(phone_number="09123456789")
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.create_user(phone_number="+98 912 345 6789")


@pytest.mark.django_db
def test_database_rejects_non_e164_phone_without_the_manager():
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.create(phone_number="09123456789")
