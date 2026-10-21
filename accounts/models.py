from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from django.utils import timezone

from .managers import UserManager


class User(AbstractBaseUser, PermissionsMixin):
    phone_number = models.CharField(max_length=16, unique=True)
    email = models.EmailField(blank=True)
    full_name = models.CharField(max_length=150, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "phone_number"
    REQUIRED_FIELDS = []

    class Meta:
        ordering = ["phone_number"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(phone_number__regex=r"^\+[1-9][0-9]{1,14}$"),
                name="accounts_user_phone_e164",
            ),
        ]

    def __str__(self):
        return self.phone_number


class OTPPurpose(models.TextChoices):
    CUSTOMER_SIGN_IN = "customer_sign_in", "Customer sign-in"


class OTPCloseReason(models.TextChoices):
    CONSUMED = "consumed", "Consumed"
    SUPERSEDED = "superseded", "Superseded by a newer code"
    DELIVERY_FAILED = "delivery_failed", "SMS delivery failed"


class OTPChallenge(models.Model):
    phone_number = models.CharField(max_length=16)
    purpose = models.CharField(
        max_length=32,
        choices=OTPPurpose.choices,
        default=OTPPurpose.CUSTOMER_SIGN_IN,
    )
    code_hash = models.CharField(max_length=64)
    attempts = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_reason = models.CharField(
        max_length=20, choices=OTPCloseReason.choices, blank=True
    )

    class Meta:
        indexes = [models.Index(fields=["phone_number", "purpose", "-created_at"])]
        constraints = [
            models.UniqueConstraint(
                fields=["phone_number", "purpose"],
                condition=models.Q(closed_at__isnull=True),
                name="accounts_otp_one_open_per_phone_purpose",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(closed_at__isnull=True, closed_reason="")
                    | (models.Q(closed_at__isnull=False) & ~models.Q(closed_reason=""))
                ),
                name="accounts_otp_closed_has_reason",
            ),
        ]

    def __str__(self):
        return f"OTP for {self.phone_number} ({self.purpose})"
