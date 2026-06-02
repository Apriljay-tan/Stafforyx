from functools import wraps

from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import PermissionDenied


def has_module_access(user, permission_name):
    if not user.is_authenticated:
        return False

    if user.is_superuser:
        return True

    profile = getattr(user, 'stafforyx_profile', None)
    if profile is None:
        return False

    if profile.role == 'super_admin':
        return True

    if not profile.is_active_stafforyx:
        return False

    return bool(getattr(profile, permission_name, False))


def is_employee_only_user(user):
    """True for portal-only employees who must never reach management pages.

    Such a user is authenticated, is not a superuser, has a Stafforyx profile,
    and that profile's role is ``employee``. These users are confined to the
    Employee Portal and are redirected there instead of being shown an Access
    Restricted (403) page.
    """
    if not getattr(user, 'is_authenticated', False):
        return False
    if user.is_superuser:
        return False
    profile = getattr(user, 'stafforyx_profile', None)
    if profile is None:
        return False
    return profile.role == 'employee'


def module_access_required(permission_name):
    def decorator(view_func):
        @login_required
        @wraps(view_func)
        def wrapped_view(request, *args, **kwargs):
            if has_module_access(request.user, permission_name):
                return view_func(request, *args, **kwargs)
            raise PermissionDenied
        return wrapped_view
    return decorator


def super_admin_required(view_func):
    return user_passes_test(
        lambda user: user.is_authenticated and (
            user.is_superuser or
            getattr(getattr(user, 'stafforyx_profile', None), 'role', None) == 'super_admin'
        )
    )(view_func)


def hr_or_super_admin_required(view_func):
    return user_passes_test(
        lambda user: user.is_authenticated and (
            user.is_superuser or
            getattr(getattr(user, 'stafforyx_profile', None), 'role', None) in ['super_admin', 'hr_admin']
        )
    )(view_func)
