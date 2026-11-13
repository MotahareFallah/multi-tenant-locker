from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import connection, transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.exceptions import APIException, NotFound
from rest_framework.exceptions import ValidationError as APIValidationError
from rest_framework.generics import ListCreateAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Membership, Organization
from .permissions import IsOrgAdmin
from .serializers import (
    MemberCreateSerializer,
    MemberSerializer,
    MemberUpdateSerializer,
)
from .services import (
    LastAdminError,
    add_member_by_phone,
    change_role,
    deactivate_member,
    get_active_membership,
    reactivate_member,
)


class TenantContextMixin:
    """Activates `request.tenant`'s schema for the handler and always undoes it.

    Subclasses set `request.tenant` in `check_permissions`. The schema is activated
    only after authentication, permissions and throttles, which all run on `public`.
    """

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        connection.set_tenant(request.tenant)

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


class TenantViewMixin(TenantContextMixin):
    """Tenant handling for staff views under /api/v1/orgs/<slug>/.

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
        request.tenant = membership.organization
        super().check_permissions(request)


class CustomerTenantMixin(TenantContextMixin):
    """Tenant handling for customer views under /api/v1/orgs/<slug>/my/.

    A customer is not a member of the organization, so there is no membership and
    no role here. Any signed-in user can activate the schema of any existing
    organization. The view alone must make sure that only the caller's own data is
    reachable (for parcels: `recipient_phone == request.user.phone_number`).
    An unknown slug gives 404.
    """

    def check_permissions(self, request):
        if not request.user or not request.user.is_authenticated:
            self.permission_denied(request)
        organization = Organization.objects.filter(slug=self.kwargs["slug"]).first()
        if organization is None:
            raise NotFound()
        request.tenant = organization
        super().check_permissions(request)


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


class LastAdmin(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "An organization must keep at least one active admin."
    default_code = "last_admin"


class MemberListCreateView(TenantViewMixin, ListCreateAPIView):
    """List the organization's memberships and add a member, for its admins.

    Memberships live in `public`, so the schema does not separate organizations
    here: the filter on the caller's own organization does.
    """

    permission_classes = [IsOrgAdmin]
    serializer_class = MemberSerializer

    def get_queryset(self):
        return (
            Membership.objects.filter(organization=self.request.membership.organization)
            .select_related("user")
            .order_by("id")
        )

    def create(self, request, *args, **kwargs):
        serializer = MemberCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            membership = add_member_by_phone(
                organization=request.membership.organization,
                phone_number=serializer.validated_data["phone_number"],
                role=serializer.validated_data["role"],
            )
        except DjangoValidationError as exc:
            raise APIValidationError(exc.messages) from exc
        return Response(
            MemberSerializer(membership).data, status=status.HTTP_201_CREATED
        )


class MemberDetailView(TenantViewMixin, APIView):
    """Change a member's role or active flag. There is no delete: deactivate."""

    permission_classes = [IsOrgAdmin]

    def patch(self, request, slug, pk):
        # Filtering on the caller's organization makes another organization's
        # member look exactly like a member that does not exist.
        membership = get_object_or_404(
            Membership.objects.filter(
                organization=request.membership.organization
            ).select_related("user"),
            pk=pk,
        )
        serializer = MemberUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            with transaction.atomic():
                if "role" in data:
                    membership = change_role(membership, data["role"])
                if "is_active" in data:
                    change = reactivate_member if data["is_active"] else deactivate_member
                    membership = change(membership)
        except LastAdminError:
            raise LastAdmin from None
        except DjangoValidationError as exc:
            raise APIValidationError(exc.messages) from exc
        membership = Membership.objects.select_related("user").get(pk=membership.pk)
        return Response(MemberSerializer(membership).data)
