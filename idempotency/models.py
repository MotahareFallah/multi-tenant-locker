from django.db import models


class IdempotencyKey(models.Model):
    """The remembered outcome of one client request (ADR-0003).

    Lives in the tenant schema. A row without `response_status` means the request
    is still running. `user_id` is a plain number, not a foreign key, because users
    live in the public schema.
    """

    key = models.CharField(max_length=255)
    endpoint = models.CharField(max_length=128)
    user_id = models.BigIntegerField()
    request_hash = models.CharField(max_length=64)
    response_status = models.PositiveSmallIntegerField(null=True, blank=True)
    response_body = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["key", "endpoint", "user_id"],
                name="idempotency_one_key_per_endpoint_and_user",
            ),
            models.CheckConstraint(
                condition=models.Q(response_status__isnull=True)
                | models.Q(response_status__range=(100, 599)),
                name="idempotency_response_status_valid",
            ),
        ]

    def __str__(self):
        return f"{self.endpoint}:{self.key}"
