from django.db import models
from django_tenants.models import DomainMixin, TenantMixin


class Organization(TenantMixin):
    name = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)

    auto_create_schema = True

    def __str__(self):
        return self.name


class Domain(DomainMixin):
    def __str__(self):
        return self.domain
