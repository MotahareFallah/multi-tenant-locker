from rest_framework import serializers

from accounts.serializers import PhoneNumberField

from .models import Membership, Role


class MemberSerializer(serializers.ModelSerializer):
    phone_number = serializers.CharField(source="user.phone_number", read_only=True)
    full_name = serializers.CharField(source="user.full_name", read_only=True)

    class Meta:
        model = Membership
        fields = ["id", "phone_number", "full_name", "role", "is_active", "created_at"]
        read_only_fields = fields


class MemberCreateSerializer(serializers.Serializer):
    phone_number = PhoneNumberField()
    role = serializers.ChoiceField(choices=Role.choices)


class MemberUpdateSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=Role.choices, required=False)
    is_active = serializers.BooleanField(required=False)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Provide role and/or is_active.")
        return attrs
