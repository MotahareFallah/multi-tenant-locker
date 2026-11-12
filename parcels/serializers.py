from rest_framework import serializers

from accounts.serializers import PhoneNumberField
from lockers.models import CompartmentSize, Locker

from .models import Parcel, ParcelEvent


class ParcelEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = ParcelEvent
        fields = ["from_status", "to_status", "actor", "reason", "created_at"]


class ParcelSerializer(serializers.ModelSerializer):
    """What staff see. The pickup code hash is never part of it."""

    locker = serializers.SlugRelatedField(slug_field="code", read_only=True)
    compartment = serializers.SerializerMethodField()

    class Meta:
        model = Parcel
        fields = [
            "tracking_code",
            "locker",
            "compartment",
            "recipient_phone",
            "size",
            "status",
            "pickup_attempts",
            "wrong_code_attempts",
            "expires_at",
            "created_at",
        ]

    def get_compartment(self, parcel):
        return parcel.compartment.number if parcel.compartment_id else None


class ParcelDetailSerializer(ParcelSerializer):
    events = ParcelEventSerializer(many=True, read_only=True)

    class Meta(ParcelSerializer.Meta):
        fields = [*ParcelSerializer.Meta.fields, "events"]


class ParcelCreateSerializer(serializers.Serializer):
    locker = serializers.SlugRelatedField(
        slug_field="code", queryset=Locker.objects.all()
    )
    recipient_phone = PhoneNumberField()
    size = serializers.ChoiceField(choices=CompartmentSize.choices)
