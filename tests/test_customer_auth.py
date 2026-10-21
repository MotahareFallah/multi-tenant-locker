import pytest

from accounts import customer_auth, otp
from accounts.models import User

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


def test_inactive_customer_cannot_sign_in(fixed_codes):
    User.objects.create_user(phone_number=PHONE, is_active=False)
    customer_auth.request_customer_code(PHONE)
    with pytest.raises(otp.InvalidOTP):
        customer_auth.sign_in_customer(PHONE, "111111")
