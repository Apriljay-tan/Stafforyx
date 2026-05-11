from django.shortcuts import redirect
from django.contrib import messages

from .context_processors import is_license_active

# ── Superuser-only admin guard ────────────────────────────────────────────────

class SuperuserAdminMiddleware:
    """
    Restrict /admin/ to superusers only.
    Django Admin is for SYNTRIX PH / developer maintenance — not for client users.
    - Authenticated non-superusers  → redirected to dashboard with an error message.
    - Unauthenticated visitors      → redirected to the app login page.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith('/admin/') and not request.user.is_superuser:
            if request.user.is_authenticated:
                messages.error(
                    request,
                    'Admin Panel access is restricted to system administrators.',
                )
                return redirect('/')
            # Send unauthenticated visitors to the app login, not Django admin login
            return redirect('/accounts/login/')
        return self.get_response(request)


# ── License read-only guard ───────────────────────────────────────────────────

# POST requests to these path prefixes are always allowed regardless of license state.
# /admin/    — Django admin (superuser-only, handled above)
# /accounts/ — login, logout, user management
# /licenses/ — license status and activation
_EXEMPT_PREFIXES = ('/admin/', '/accounts/', '/licenses/')

_BLOCKED_MSG = (
    'Your Stafforyx HR license is expired or inactive. '
    'Please renew your license to make changes.'
)


class LicenseReadOnlyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._should_block(request):
            messages.error(request, _BLOCKED_MSG)
            return redirect('licenses:license_status')
        return self.get_response(request)

    def _should_block(self, request):
        if request.method != 'POST':
            return False
        if not request.user.is_authenticated:
            return False
        if any(request.path.startswith(p) for p in _EXEMPT_PREFIXES):
            return False
        return not is_license_active()
