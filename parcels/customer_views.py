"""Endpoints for the recipient of a parcel (ADR-0004).

A customer is not a member of the organization. Whatever they can reach is
decided by one rule: the parcel's recipient phone is their own phone number.
A parcel of somebody else is answered exactly like a parcel that does not
exist.
"""

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from accounts.throttling import PickupThrottle
from config.pagination import StandardPagination
from devices.base import DeviceTimeout
from idempotency.api import keyed_response
from organizations.views import CustomerTenantMixin

from .device import get_device
from .models import Parcel
from .pickup import PickupBlocked, WrongPickupCode, pickup_parcel
from .serializers import CustomerParcelSerializer, PickupSerializer
from .state_machine import InvalidTransition
from .views import refusal


class MyParcelsMixin(CustomerTenantMixin):
    permission_classes = [IsAuthenticated]
    serializer_class = CustomerParcelSerializer

    def get_queryset(self):
        return Parcel.objects.filter(
            recipient_phone=self.request.user.phone_number
        ).select_related("locker", "compartment")


class MyParcelListView(MyParcelsMixin, ListAPIView):
    pagination_class = StandardPagination

    def get_queryset(self):
        return super().get_queryset().order_by("-created_at", "-id")


class MyParcelDetailView(MyParcelsMixin, RetrieveAPIView):
    lookup_field = "tracking_code"


class MyParcelPickupView(MyParcelsMixin, APIView):
    """Open the door with the pickup code. Run once per Idempotency-Key.

    Every answer the client may see again is returned, so it is stored and
    replayed. After a device failure the code is already spent: repeating the
    request replays the failure, and a new attempt needs a newly sent code.
    """

    throttle_classes = [PickupThrottle]

    def post(self, request, slug, tracking_code):
        parcel = get_object_or_404(self.get_queryset(), tracking_code=tracking_code)
        serializer = PickupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        code = serializer.validated_data["code"]
        actor = f"customer:{request.user.pk}"

        def handler():
            try:
                outcome = pickup_parcel(
                    parcel.pk, code, device=get_device(), actor=actor
                )
            except WrongPickupCode as exc:
                return status.HTTP_403_FORBIDDEN, {
                    "code": "wrong_pickup_code",
                    "detail": str(exc),
                    "attempts_left": exc.attempts_left,
                }
            except PickupBlocked as exc:
                return status.HTTP_403_FORBIDDEN, {
                    "code": "pickup_blocked",
                    "detail": str(exc),
                }
            except InvalidTransition as exc:
                return refusal(exc)

            current = self.get_queryset().get(pk=outcome.parcel.pk)
            data = CustomerParcelSerializer(current).data
            if outcome.delivered:
                return status.HTTP_200_OK, data
            if isinstance(outcome.device_error, DeviceTimeout):
                return status.HTTP_504_GATEWAY_TIMEOUT, {
                    "code": "device_timeout",
                    "detail": "The locker did not answer. The door may have opened; "
                    "contact the operator.",
                    "parcel": data,
                }
            return status.HTTP_502_BAD_GATEWAY, {
                "code": "device_fault",
                "detail": "The locker reported an error. Contact the operator.",
                "parcel": data,
            }

        return keyed_response(
            request, endpoint=f"parcel.pickup:{tracking_code}", handler=handler
        )
