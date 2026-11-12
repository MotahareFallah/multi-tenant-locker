"""Glue between DRF views and `execute()`: the header and the error responses."""

from rest_framework import status
from rest_framework.response import Response

from .services import (
    IdempotencyKeyReused,
    InvalidIdempotencyKey,
    RequestInProgress,
    execute,
)

HEADER = "Idempotency-Key"
REPLAY_HEADER = "Idempotent-Replayed"


def _refusal(status_code, code, detail):
    return Response({"code": code, "detail": detail}, status=status_code)


def keyed_response(request, *, endpoint, handler):
    """Run `handler` once per Idempotency-Key and return its response.

    `handler` returns `(status_code, body)`. A response that is replayed carries
    `Idempotent-Replayed: true`.
    """
    key = request.headers.get(HEADER)
    if key is None:
        return _refusal(
            status.HTTP_400_BAD_REQUEST,
            "idempotency_key_required",
            f"The {HEADER} header is required.",
        )
    try:
        result = execute(
            key=key,
            endpoint=endpoint,
            user_id=request.user.pk,
            request_data=request.data,
            handler=handler,
        )
    except InvalidIdempotencyKey as exc:
        return _refusal(status.HTTP_400_BAD_REQUEST, "invalid_idempotency_key", str(exc))
    except IdempotencyKeyReused as exc:
        return _refusal(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "idempotency_key_reused", str(exc)
        )
    except RequestInProgress as exc:
        return _refusal(status.HTTP_409_CONFLICT, "request_in_progress", str(exc))
    response = Response(result.body, status=result.status_code)
    if result.replayed:
        response[REPLAY_HEADER] = "true"
    return response
