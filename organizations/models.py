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
