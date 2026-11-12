from django.urls import path

from . import views

urlpatterns = [
    path("parcels/", views.ParcelListCreateView.as_view()),
    path("parcels/<str:tracking_code>/", views.ParcelDetailView.as_view()),
    path(
        "parcels/<str:tracking_code>/deposit/", views.ParcelDepositView.as_view()
    ),
    path(
        "parcels/<str:tracking_code>/pickup-code/",
        views.ParcelPickupCodeView.as_view(),
    ),
]
