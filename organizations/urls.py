from django.urls import path

from . import views

urlpatterns = [
    path("", views.OrganizationView.as_view(), name="organization"),
    path("members/", views.MemberListCreateView.as_view(), name="member-list"),
    path("members/<int:pk>/", views.MemberDetailView.as_view(), name="member-detail"),
]
