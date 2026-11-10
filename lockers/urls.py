from django.urls import path

from . import views

urlpatterns = [
    path("lockers/", views.LockerListCreateView.as_view()),
    path("lockers/<slug:code>/", views.LockerDetailView.as_view()),
    path("lockers/<slug:code>/compartments/", views.CompartmentCreateView.as_view()),
    path(
        "lockers/<slug:code>/compartments/<int:number>/",
        views.CompartmentDetailView.as_view(),
    ),
]
