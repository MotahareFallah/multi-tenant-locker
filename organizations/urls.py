from django.urls import path

from . import views

urlpatterns = [
    path("", views.OrganizationView.as_view(), name="organization"),
]
