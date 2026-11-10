import secrets

from django.db import models

from lockers.models import Compartment, CompartmentSize, Locker


class ParcelStatus(models.TextChoices):
    CREATED = "CREATED", "Created"
    STORED = "STORED", "Stored"
    READY_FOR_PICKUP = "READY_FOR_PICKUP", "Ready for pickup"
    PICKUP_IN_PROGRESS = "PICKUP_IN_PROGRESS", "Pickup in progress"
    DELIVERED = "DELIVERED", "Delivered"
    EXPIRED = "EXPIRED", "Expired"
    PICKUP_FAILED = "PICKUP_FAILED", "Pickup failed"


# A parcel in one of these states is physically in a compartment.
OCCUPYING_STATUSES = [
    ParcelStatus.STORED,
    ParcelStatus.READY_FOR_PICKUP,
    ParcelStatus.PICKUP_IN_PROGRESS,
    ParcelStatus.PICKUP_FAILED,
]


def new_tracking_code():
    return secrets.token_hex(8).upper()


class Parcel(models.Model):
    """A parcel and its current state. Lives in the tenant schema (ADR-0003).

    `status` must only be changed through the state machine, never assigned
    directly.
    """

    tracking_code = models.CharField(
        max_length=32, unique=True, default=new_tracking_code
    )
    locker = models.ForeignKey(
        Locker, on_delete=models.PROTECT, related_name="parcels"
    )
    compartment = models.ForeignKey(
        Compartment,
        on_delete=models.PROTECT,
        related_name="parcels",
        null=True,
        blank=True,
    )
    recipient_phone = models.CharField(max_length=16)
    size = models.CharField(max_length=10, choices=CompartmentSize.choices)
    status = models.CharField(
        max_length=20,
        choices=ParcelStatus.choices,
        default=ParcelStatus.CREATED,
        db_index=True,
    )
    pickup_code_hash = models.CharField(max_length=64, blank=True, default="")
    pickup_attempts = models.PositiveSmallIntegerField(default=0)
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=ParcelStatus.values),
                name="parcels_status_valid",
            ),
            models.UniqueConstraint(
                fields=["compartment"],
                condition=models.Q(status__in=OCCUPYING_STATUSES),
                name="parcels_one_active_parcel_per_compartment",
            ),
            models.CheckConstraint(
                condition=models.Q(compartment__isnull=False)
                | ~models.Q(status__in=OCCUPYING_STATUSES),
                name="parcels_occupying_status_has_compartment",
            ),
        ]

    def __str__(self):
        return self.tracking_code


class ParcelEvent(models.Model):
    """Append-only history of a parcel's transitions."""

    parcel = models.ForeignKey(
        Parcel, on_delete=models.PROTECT, related_name="events"
    )
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20, choices=ParcelStatus.choices)
    actor = models.CharField(max_length=64)
    reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.parcel_id}: {self.from_status or '-'} -> {self.to_status}"
