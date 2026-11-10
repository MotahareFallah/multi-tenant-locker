from django.db import models


class Locker(models.Model):
    """A physical locker station. Lives in the tenant schema."""

    code = models.SlugField(max_length=63, unique=True)
    name = models.CharField(max_length=120)
    address = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.code


class CompartmentSize(models.TextChoices):
    SMALL = "SMALL", "Small"
    MEDIUM = "MEDIUM", "Medium"
    LARGE = "LARGE", "Large"


class Compartment(models.Model):
    """One door of a locker. `is_active=False` means out of service."""

    locker = models.ForeignKey(
        Locker, on_delete=models.PROTECT, related_name="compartments"
    )
    number = models.PositiveSmallIntegerField()
    size = models.CharField(max_length=10, choices=CompartmentSize.choices)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["locker", "number"],
                name="lockers_unique_compartment_number_per_locker",
            ),
            models.CheckConstraint(
                condition=models.Q(number__gte=1),
                name="lockers_compartment_number_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(size__in=["SMALL", "MEDIUM", "LARGE"]),
                name="lockers_compartment_size_valid",
            ),
        ]

    def __str__(self):
        return f"{self.locker_id}/{self.number}"
