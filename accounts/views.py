from rest_framework import status
from rest_framework.exceptions import APIException, Throttled
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenBlacklistView, TokenRefreshView

from . import customer_auth, otp
from .serializers import OTPRequestSerializer, OTPVerifySerializer
from .sms import SmsDeliveryError
from .throttling import OTPRequestThrottle, OTPVerifyThrottle, TokenThrottle


class InvalidCode(APIException):
    """One response for wrong, expired, used and unknown codes and inactive users."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "The code is invalid or expired."
    default_code = "invalid_code"


class SmsUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "The code could not be sent. Please try again later."
    default_code = "sms_unavailable"


class PublicAPIView(APIView):
    # No authentication at all: a stale or malformed Authorization header must
    # not turn a public request into a 401.
    authentication_classes = []
    permission_classes = [AllowAny]


class OTPRequestView(PublicAPIView):
    throttle_classes = [OTPRequestThrottle]

    def post(self, request):
        serializer = OTPRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        phone_number = serializer.validated_data["phone_number"]
        try:
            customer_auth.request_customer_code(phone_number)
        except otp.OTPThrottled as exc:
            raise Throttled(wait=exc.retry_after) from None
        except SmsDeliveryError:
            raise SmsUnavailable from None
        return Response(
            {"detail": "Verification code sent."}, status=status.HTTP_202_ACCEPTED
        )


class OTPVerifyView(PublicAPIView):
    throttle_classes = [OTPVerifyThrottle]

    def post(self, request):
        serializer = OTPVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            user = customer_auth.sign_in_customer(data["phone_number"], data["code"])
        except otp.InvalidOTP:
            raise InvalidCode from None
        refresh = RefreshToken.for_user(user)
        return Response({"refresh": str(refresh), "access": str(refresh.access_token)})


class ThrottledTokenRefreshView(TokenRefreshView):
    throttle_classes = [TokenThrottle]


class ThrottledTokenBlacklistView(TokenBlacklistView):
    """Logout: revokes a refresh token. Access tokens expire on their own."""

    throttle_classes = [TokenThrottle]
