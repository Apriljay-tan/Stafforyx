from django.shortcuts import redirect

from .access import is_employee_only_user

# Path prefixes a portal-only employee is allowed to reach. Everything else is
# redirected to the Employee Portal dashboard. Keep this list tight: it should
# only cover the portal, the IP-validated time clock, logout, and static/PWA
# assets needed to render those pages.
_EMPLOYEE_ALLOWED_PREFIXES = (
    '/portal/',               # Employee self-service portal (and all its pages)
    '/attendance/portal/',    # IP/WiFi-validated time clock used by the portal
    '/messaging/attachments/',  # Protected chat image/GIF downloads for portal users
    '/accounts/logout/',      # Logout
    '/static/',               # Static assets (CSS/JS/images)
    '/media/',                # Uploaded media (e.g. payslip/document files)
    '/service-worker.js',     # PWA service worker
    '/manifest.webmanifest',  # PWA manifest
)


class EmployeePortalOnlyMiddleware:
    """Confine portal-only employees to the Employee Portal.

    Runs after AuthenticationMiddleware so ``request.user`` is populated, and
    before any module permission checks (which live in the view decorators).
    When the logged-in user is employee-only, any request to a path outside the
    allowed portal prefixes is redirected straight to the portal dashboard. As a
    result these users never land on the management dashboard and never see an
    Access Restricted (403) page.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        if user is not None and is_employee_only_user(user):
            if not request.path.startswith(_EMPLOYEE_ALLOWED_PREFIXES):
                return redirect('portal:dashboard')
        return self.get_response(request)
