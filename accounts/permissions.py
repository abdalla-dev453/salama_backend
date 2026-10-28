from rest_framework.permissions import BasePermission


class IsSalamaAdmin(BasePermission):
    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and u.is_salama_admin)


class IsStaffMember(BasePermission):
    """An active CHW or admin (never a survivor / anonymous)."""

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and (u.is_salama_admin or u.is_chw))
