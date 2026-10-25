from django.urls import path

from . import views

urlpatterns = [
    path("otp/request/", views.OTPRequestView.as_view(), name="otp-request"),
    path("otp/verify/", views.OTPVerifyView.as_view(), name="otp-verify"),
    path("token/refresh/", views.ThrottledTokenRefreshView.as_view(), name="token-refresh"),
    path("token/blacklist/", views.ThrottledTokenBlacklistView.as_view(), name="token-blacklist"),
]
