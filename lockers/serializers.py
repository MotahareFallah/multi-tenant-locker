from rest_framework import serializers

from .models import Compartment, Locker


class CompartmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Compartment
        fields = ["number", "size", "is_active"]
        extra_kwargs = {"number": {"min_value": 1}}


class CompartmentUpdateSerializer(serializers.ModelSerializer):
    """The number and size of a compartment never change; only its switch does."""

    class Meta:
        model = Compartment
        fields = ["is_active"]
        extra_kwargs = {"is_active": {"required": True}}


class LockerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Locker
        fields = ["code", "name", "address", "is_active", "created_at"]
        read_only_fields = ["created_at"]


class LockerDetailSerializer(LockerSerializer):
    """A locker with its compartments. The code cannot be changed."""

    compartments = CompartmentSerializer(many=True, read_only=True)

    class Meta(LockerSerializer.Meta):
        fields = [*LockerSerializer.Meta.fields, "compartments"]
        read_only_fields = ["code", "created_at"]
