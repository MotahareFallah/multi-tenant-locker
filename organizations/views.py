from django.db import connection
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from .services import get_active_membership


class TenantAPIView(APIView):
    """Base class for endpoints under /api/v1/orgs/<slug>/.

    The organization's schema is activated only after the caller is authenticated and
    has an active membership there, and the connection always goes back to `public`
    when the request ends. An unknown slug, somebody else's organization and an
    inactive membership all give the same 404.
    """

    def initial(self, request, *args, **kwargs):
        # Authentication, permissions and throttles run first; the schema is still
        # `public` while they do.
        super().initial(request, *args, **kwargs)
        membership = get_active_membership(request.user, kwargs["slug"])
        if membership is None:
            raise NotFound()
        request.membership = membership
        connection.set_tenant(membership.organization)

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
