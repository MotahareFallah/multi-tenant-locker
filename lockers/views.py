from django.db import IntegrityError, transaction
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.generics import ListCreateAPIView, RetrieveUpdateAPIView
from rest_framework.response import Response

from config.pagination import StandardPagination
from organizations.permissions import IsOrgAdmin
from organizations.views import TenantAPIView, TenantViewMixin

from .models import Compartment, Locker
from .serializers import (
    CompartmentSerializer,
    CompartmentUpdateSerializer,
    LockerDetailSerializer,
    LockerSerializer,
)

UNIQUE_VIOLATION = "23505"


class LockerListCreateView(TenantViewMixin, ListCreateAPIView):
    permission_classes = [IsOrgAdmin]
    serializer_class = LockerSerializer
    pagination_class = StandardPagination
    queryset = Locker.objects.order_by("code")


class LockerDetailView(TenantViewMixin, RetrieveUpdateAPIView):
    """Read a locker, rename it or switch it on or off. No PUT, no DELETE."""

    permission_classes = [IsOrgAdmin]
    serializer_class = LockerDetailSerializer
    lookup_field = "code"
    http_method_names = ["get", "patch", "head", "options"]
    queryset = Locker.objects.prefetch_related(
        Prefetch("compartments", queryset=Compartment.objects.order_by("number"))
    )


class CompartmentCreateView(TenantAPIView):
    permission_classes = [IsOrgAdmin]

    def post(self, request, slug, code):
        locker = get_object_or_404(Locker, code=code)
        serializer = CompartmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        duplicate = ValidationError(
            {"number": ["This locker already has a compartment with this number."]}
        )
        if Compartment.objects.filter(
            locker=locker, number=serializer.validated_data["number"]
        ).exists():
            raise duplicate
        try:
            with transaction.atomic():
                compartment = Compartment.objects.create(
                    locker=locker, **serializer.validated_data
                )
        except IntegrityError as exc:
            # Two requests with the same number at once: only that is absorbed.
            if getattr(exc.__cause__, "sqlstate", None) != UNIQUE_VIOLATION:
                raise
            raise duplicate from exc
        return Response(
            CompartmentSerializer(compartment).data, status=status.HTTP_201_CREATED
        )


class CompartmentDetailView(TenantAPIView):
    permission_classes = [IsOrgAdmin]

    def _compartment(self, code, number):
        return get_object_or_404(
            Compartment.objects.filter(locker__code=code), number=number
        )

    def get(self, request, slug, code, number):
        return Response(CompartmentSerializer(self._compartment(code, number)).data)

    def patch(self, request, slug, code, number):
        compartment = self._compartment(code, number)
        serializer = CompartmentUpdateSerializer(compartment, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(CompartmentSerializer(compartment).data)
