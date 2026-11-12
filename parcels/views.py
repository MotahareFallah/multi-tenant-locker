from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.generics import ListCreateAPIView, RetrieveAPIView
from rest_framework.response import Response

from config.pagination import StandardPagination
from idempotency.api import keyed_response
from organizations.permissions import IsOrgMember
from organizations.views import TenantAPIView, TenantViewMixin

from .models import Parcel, ParcelStatus
from .serializers import (
    ParcelCreateSerializer,
    ParcelDetailSerializer,
    ParcelSerializer,
)
from .services import (
    LockerUnavailable,
    NoFreeCompartment,
    PickupCodeDeliveryFailed,
    create_parcel,
    deposit_parcel,
    send_pickup_code,
)
from .state_machine import InvalidTransition, PickupAttemptsExhausted

# Order matters: PickupAttemptsExhausted is a kind of InvalidTransition.
REFUSALS = [
    (PickupAttemptsExhausted, "pickup_attempts_exhausted"),
    (InvalidTransition, "invalid_transition"),
    (NoFreeCompartment, "no_free_compartment"),
    (LockerUnavailable, "locker_unavailable"),
]


def refusal(exc):
    """A refusal the client may see again: returned, so it is stored and replayed."""
    for error_class, code in REFUSALS:
        if isinstance(exc, error_class):
            return status.HTTP_409_CONFLICT, {"code": code, "detail": str(exc)}
    raise exc


def parcels():
    return Parcel.objects.select_related("locker", "compartment")


class ParcelListCreateView(TenantViewMixin, ListCreateAPIView):
    permission_classes = [IsOrgMember]
    serializer_class = ParcelSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        queryset = parcels().order_by("-created_at", "-id")
        wanted = self.request.query_params.get("status")
        if wanted is not None:
            if wanted not in ParcelStatus.values:
                raise ValidationError(
                    {"status": [f"Unknown status. Use one of: {', '.join(ParcelStatus.values)}."]}
                )
            queryset = queryset.filter(status=wanted)
        return queryset

    def create(self, request, *args, **kwargs):
        serializer = ParcelCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        actor = f"user:{request.user.pk}"

        def handler():
            try:
                parcel = create_parcel(
                    locker=data["locker"],
                    recipient_phone=data["recipient_phone"],
                    size=data["size"],
                    actor=actor,
                )
            except LockerUnavailable as exc:
                return refusal(exc)
            return status.HTTP_201_CREATED, ParcelSerializer(parcel).data

        return keyed_response(request, endpoint="parcel.create", handler=handler)


class ParcelDetailView(TenantViewMixin, RetrieveAPIView):
    permission_classes = [IsOrgMember]
    serializer_class = ParcelDetailSerializer
    lookup_field = "tracking_code"
    queryset = Parcel.objects.select_related("locker", "compartment").prefetch_related(
        "events"
    )


class ParcelActionView(TenantAPIView):
    """A state-changing POST on one parcel, run once per Idempotency-Key."""

    permission_classes = [IsOrgMember]
    action_name = ""

    def perform(self, parcel, actor):
        raise NotImplementedError

    def post(self, request, slug, tracking_code):
        parcel = get_object_or_404(Parcel, tracking_code=tracking_code)
        actor = f"user:{request.user.pk}"
        return keyed_response(
            request,
            endpoint=f"{self.action_name}:{tracking_code}",
            handler=lambda: self.perform(parcel, actor),
        )


class ParcelDepositView(ParcelActionView):
    action_name = "parcel.deposit"

    def perform(self, parcel, actor):
        try:
            deposited = deposit_parcel(parcel.pk, actor=actor)
        except (InvalidTransition, NoFreeCompartment, LockerUnavailable) as exc:
            return refusal(exc)
        return status.HTTP_200_OK, ParcelSerializer(deposited).data


class ParcelPickupCodeView(ParcelActionView):
    """Text a new pickup code to the recipient. The code is never in the response."""

    action_name = "parcel.pickup_code"

    def perform(self, parcel, actor):
        try:
            send_pickup_code(parcel.pk, actor=actor)
        except InvalidTransition as exc:
            return refusal(exc)
        return status.HTTP_200_OK, ParcelSerializer(parcels().get(pk=parcel.pk)).data

    def post(self, request, slug, tracking_code):
        try:
            return super().post(request, slug, tracking_code)
        except PickupCodeDeliveryFailed:
            # Not stored: the key is released, so the same request can be repeated.
            return Response(
                {
                    "code": "sms_delivery_failed",
                    "detail": "The code could not be sent. Repeat the request.",
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )
