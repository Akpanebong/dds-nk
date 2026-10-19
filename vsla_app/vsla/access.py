from functools import wraps
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect


def can_access_vsla(user):
    if not user.is_authenticated or not getattr(user, "is_active", True):
        return False
    # Staff, interns and volunteers can use VSLA as part of the integrated
    # system. VSLA-only accounts are also restricted to this module by type.
    return getattr(user, "user_type", "Staff") in {"Staff", "Intern", "Volunteer", "VSLA"}


def vsla_access_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("login")
        if not can_access_vsla(request.user):
            raise PermissionDenied("You do not have permission to access VSLA Management.")
        return view_func(request, *args, **kwargs)
    return _wrapped
