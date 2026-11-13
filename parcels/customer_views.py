"""Endpoints for the recipient of a parcel (ADR-0004).

A customer is not a member of the organization. Whatever they can reach is
decided by one rule: the parcel's recipient phone is their own phone number.
A parcel of somebody else is answered exactly like a parcel that does not
exist.
"""

from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.permissions import IsAuthenticated

from config.pagination import StandardPagination
from organizations.views import CustomerTenantMixin

from .models import Parcel
from .serializers import CustomerParcelSerializer


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
