import pytest
from django.db import IntegrityError, transaction

from accounts import customer_auth, otp
from accounts.models import OTPChallenge, OTPCloseReason, User

PHONE = "09123456789"
E164 = "+989123456789"

pytestmark = pytest.mark.django_db


def test_sign_in_registers_a_new_customer_without_privileges(fixed_codes):
    customer_auth.request_customer_code(PHONE)
    user = customer_auth.sign_in_customer(PHONE, "111111")
    assert user.phone_number == E164
    assert not user.has_usable_password()
    assert not user.is_staff
    assert not user.is_superuser
    assert User.objects.count() == 1


def test_sign_in_returns_the_existing_customer(fixed_codes):
    existing = User.objects.create_user(phone_number=PHONE)
    customer_auth.request_customer_code(PHONE)
    assert customer_auth.sign_in_customer(PHONE, "111111") == existing
    assert User.objects.count() == 1


def test_wrong_code_does_not_create_a_customer(fixed_codes):
    customer_auth.request_customer_code(PHONE)
    with pytest.raises(otp.InvalidOTP):
        customer_auth.sign_in_customer(PHONE, "999999")
    assert not User.objects.exists()


def test_inactive_customer_is_rejected_and_the_code_is_consumed(fixed_codes):
    User.objects.create_user(phone_number=PHONE, is_active=False)
    customer_auth.request_customer_code(PHONE)
    with pytest.raises(otp.InvalidOTP):
        customer_auth.sign_in_customer(PHONE, "111111")
    assert OTPChallenge.objects.get().closed_reason == OTPCloseReason.CONSUMED
    with pytest.raises(otp.InvalidOTP):
        customer_auth.sign_in_customer(PHONE, "111111")


def test_unexpected_integrity_errors_are_not_swallowed(monkeypatch):
    def broken_create_user(*args, **kwargs):
        raise IntegrityError("some other constraint")

    monkeypatch.setattr(User.objects, "create_user", broken_create_user)
    with pytest.raises(IntegrityError):
        customer_auth.get_or_create_user(E164)


def test_a_real_duplicate_phone_is_recognized_as_a_unique_violation():
    User.objects.create_user(phone_number=PHONE)
    with pytest.raises(IntegrityError) as exc_info, transaction.atomic():
        User.objects.create_user(phone_number=PHONE)
    assert customer_auth._is_unique_violation(exc_info.value)


def test_a_check_constraint_violation_is_not_a_unique_violation():
    with pytest.raises(IntegrityError) as exc_info, transaction.atomic():
        User.objects.create(phone_number="09123456789")
    assert not customer_auth._is_unique_violation(exc_info.value)


def test_an_error_without_a_database_cause_is_not_a_unique_violation():
    assert not customer_auth._is_unique_violation(IntegrityError("other"))
