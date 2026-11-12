from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/auth/", include("accounts.urls")),
    path("api/v1/orgs/<slug:slug>/", include("organizations.urls")),
    path("api/v1/orgs/<slug:slug>/", include("lockers.urls")),
    path("api/v1/orgs/<slug:slug>/", include("parcels.urls")),
]
