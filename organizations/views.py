from django.db import connection
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from .services import get_active_membership


class TenantViewMixin:
    """Tenant handling for any DRF view or viewset under /api/v1/orgs/<slug>/.

    List it before the DRF base class: `class LockerList(TenantViewMixin, ListAPIView)`.

    Order of events for a request:

    1. Authentication (always required, whatever `permission_classes` a subclass sets).
    2. The caller's active membership for the slug is loaded and put on
       `request.membership`. An unknown slug, somebody else's organization and an
       inactive membership all give the same 404.
    3. The subclass's permission classes run and can use `request.membership`
       (a member without the right role gets a 403).
    4. Throttles run, still on the `public` schema.
    5. Only then is the organization's schema activated and the handler run.

    The connection always goes back to `public` when the request ends.
    """

    def check_permissions(self, request):
        if not request.user or not request.user.is_authenticated:
            self.permission_denied(request)
        membership = get_active_membership(request.user, self.kwargs["slug"])
        if membership is None:
            raise NotFound()
        request.membership = membership
        super().check_permissions(request)

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        connection.set_tenant(request.membership.organization)

    def dispatch(self, request, *args, **kwargs):
        try:
            response = super().dispatch(request, *args, **kwargs)
            # DRF renders after dispatch returns. Render now, while the tenant
            # schema is active, so lazy querysets in the response data are
            # evaluated in the right schema.
            if hasattr(response, "render") and not response.is_rendered:
                response.render()
            return response
        finally:
            connection.set_schema_to_public()


class TenantAPIView(TenantViewMixin, APIView):
    """For plain endpoints; use the mixin directly with generic views and viewsets."""


class OrganizationView(TenantAPIView):
    def get(self, request, slug):
        membership = request.membership
        return Response(
            {
                "slug": membership.organization.slug,
                "name": membership.organization.name,
                "role": membership.role,
            }
        )
