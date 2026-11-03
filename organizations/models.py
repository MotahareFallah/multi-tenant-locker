from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django_tenants.models import TenantMixin

slug_validator = RegexValidator(
    r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    "Use lowercase letters, digits and single hyphens.",
)


class Organization(TenantMixin):
    """A tenant: one PostgreSQL schema per organization (see ADR-0002)."""

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=63, unique=True, validators=[slug_validator])
    created_at = models.DateTimeField(auto_now_add=True)

    # Create the schema on first save; never drop data automatically.
    auto_create_schema = True
    auto_drop_schema = False

    def __str__(self):
        return self.name


class Role(models.TextChoices):
    ADMIN = "admin", "Admin"
    OPERATOR = "operator", "Operator"


class Membership(models.Model):
    """What a user may do in one organization. Lives in the public schema.

    Verifying a phone number proves ownership only; every organization permission
    comes from a row here.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,  # deactivate users instead of deleting them
        related_name="memberships",
    )
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="memberships"
    )
    role = models.CharField(max_length=16, choices=Role.choices)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "organization"],
                name="organizations_one_membership_per_user_org",
            ),
            models.CheckConstraint(
                condition=models.Q(role__in=Role.values),
                name="organizations_membership_role_valid",
            ),
        ]

    def __str__(self):
        return f"{self.user_id} @ {self.organization_id} ({self.role})"
