"""Run a client request at most once per Idempotency-Key (ADR-0003).

`execute()` works in three steps, so that nothing is locked while the real work
runs (a pickup talks to hardware):

1. claim the key in a short transaction of its own;
2. run the handler, outside any transaction;
3. store the response in another short transaction.

The handler returns `(status_code, body)`. Refusals the client should see again
(a wrong code, a conflict) are returned, not raised, so they are stored and
replayed like any other response. An exception means something unexpected went
wrong: the key is released so the client can send the request again.

If the process dies between steps 1 and 3, the key stays "running" until it
expires. The request is never run twice; the client has to use a new key.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from idempotency.models import IdempotencyKey

MAX_KEY_LENGTH = 255


class IdempotencyError(Exception):
    """Base class for the ways a keyed request can be refused."""


class InvalidIdempotencyKey(IdempotencyError):
    """The key is missing, too long or has odd characters (HTTP 400)."""


class IdempotencyKeyReused(IdempotencyError):
    """The key was already used for a different request (HTTP 422)."""


class RequestInProgress(IdempotencyError):
    """The same request is still running (HTTP 409)."""


@dataclass(frozen=True)
class IdempotentResponse:
    status_code: int
    body: object
    replayed: bool


def hash_request(request_data):
    canonical = json.dumps(
        request_data, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _validate_key(key):
    if (
        not isinstance(key, str)
        or not 1 <= len(key) <= MAX_KEY_LENGTH
        or key != key.strip()
        or not key.isprintable()
    ):
        raise InvalidIdempotencyKey(
            f"The key must be 1-{MAX_KEY_LENGTH} printable characters "
            "without leading or trailing spaces."
        )


def _claim(lookup, request_hash):
    """Return None if this request now owns the key, else the stored response."""
    for _ in range(3):
        now = timezone.now()
        expires_at = now + timedelta(hours=settings.IDEMPOTENCY_TTL_HOURS)
        try:
            with transaction.atomic():
                IdempotencyKey.objects.create(
                    **lookup, request_hash=request_hash, expires_at=expires_at
                )
            return None
        except IntegrityError:
            pass  # the key exists; look at it below

        with transaction.atomic():
            record = IdempotencyKey.objects.select_for_update().filter(**lookup).first()
            if record is None:
                continue  # it was released in the meantime; try to claim again
            if record.expires_at <= now:
                record.request_hash = request_hash
                record.response_status = None
                record.response_body = None
                record.created_at = now
                record.expires_at = expires_at
                record.save()
                return None
            if record.request_hash != request_hash:
                raise IdempotencyKeyReused(
                    "This Idempotency-Key was already used for a different request."
                )
            if record.response_status is None:
                raise RequestInProgress("The same request is still being processed.")
            return IdempotentResponse(
                record.response_status, record.response_body, replayed=True
            )
    raise RequestInProgress("Could not claim the key; try again.")


def execute(*, key, endpoint, user_id, request_data, handler):
    """Run `handler` once for this key, or replay its stored response."""
    if connection.in_atomic_block:
        raise RuntimeError("execute() must not run inside a transaction.")
    _validate_key(key)

    lookup = {"key": key, "endpoint": endpoint, "user_id": user_id}
    replay = _claim(lookup, hash_request(request_data))
    if replay is not None:
        return replay

    try:
        status_code, body = handler()
        if not (isinstance(status_code, int) and 100 <= status_code <= 599):
            raise ValueError(f"The handler returned an invalid status: {status_code!r}")
        json.dumps(body)  # fail here, not while saving, if it cannot be stored
    except BaseException:
        IdempotencyKey.objects.filter(**lookup).delete()
        raise

    IdempotencyKey.objects.filter(**lookup).update(
        response_status=status_code, response_body=body
    )
    return IdempotentResponse(status_code, body, replayed=False)


def purge_expired_keys(now=None):
    """Delete expired records. Returns how many were removed."""
    now = now or timezone.now()
    deleted, _ = IdempotencyKey.objects.filter(expires_at__lte=now).delete()
    return deleted
