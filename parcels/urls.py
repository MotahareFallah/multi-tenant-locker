from django.urls import path

from . import customer_views, views

urlpatterns = [
    path("my/parcels/", customer_views.MyParcelListView.as_view()),
    path(
        "my/parcels/<str:tracking_code>/", customer_views.MyParcelDetailView.as_view()
    ),
    path(
        "my/parcels/<str:tracking_code>/pickup/",
        customer_views.MyParcelPickupView.as_view(),
    ),
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
