from rest_framework.permissions import BasePermission


class IsSuperAdmin(BasePermission):
    message = "Chỉ Super Admin được truy cập."

    def has_permission(self, request, view):
        user = request.user

        if not user.is_authenticated:
            return False

        if not user.is_active:
            return False

        return user.is_staff and user.is_superuser
