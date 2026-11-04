from rest_framework.permissions import BasePermission

from .models import Role


class HasRole(BasePermission):
    """Allow members whose role is in `allowed_roles`.

    Needs TenantViewMixin, which puts the caller's membership on the request. It fails
    closed: without a membership the answer is no.
    """

    allowed_roles = ()

    def has_permission(self, request, view):
        membership = getattr(request, "membership", None)
        return membership is not None and membership.role in self.allowed_roles


class IsOrgMember(HasRole):
    """Any active member, whatever their role."""

    allowed_roles = tuple(Role.values)


class IsOrgAdmin(HasRole):
    """Admins only. Admins can do everything operators can."""

    allowed_roles = (Role.ADMIN,)
