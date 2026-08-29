from functools import wraps

from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect


def admin_required(view_func):
    """
    Allow access only to authenticated users with the ADMIN role.
    Students receive a permission-denied response rather than being logged out.
    """

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("admin_portal:login")

        if not request.user.is_admin_user:
            raise PermissionDenied

        return view_func(request, *args, **kwargs)

    return wrapper
