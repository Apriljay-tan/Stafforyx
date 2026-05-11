from django.shortcuts import redirect
from django.contrib import messages

from .context_processors import is_license_active

# POST requests to these path prefixes are always allowed regardless of license state.
# /admin/    — Django admin (avoid breaking dev workflow)
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
