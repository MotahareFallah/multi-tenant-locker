from rest_framework import serializers

from .models import Membership


class MemberSerializer(serializers.ModelSerializer):
    phone_number = serializers.CharField(source="user.phone_number", read_only=True)
    full_name = serializers.CharField(source="user.full_name", read_only=True)

    class Meta:
        model = Membership
        fields = ["id", "phone_number", "full_name", "role", "is_active", "created_at"]
        read_only_fields = fields
