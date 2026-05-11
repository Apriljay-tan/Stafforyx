from .models import License

_WARN_DAYS = 7


def is_license_active():
    """Return True if the most recent license is valid and not expired/suspended."""
    lic = License.objects.order_by('-created_at').first()
    if lic is None:
        return False
    if lic.status in ('expired', 'suspended'):
        return False
    if lic.is_expired:
        return False
    return True


def license_banner(request):
    """
    Inject `license_banner` into every template context rendered by base.html.
    Returns None (no banner) for admin paths, unauthenticated users,
    lifetime licenses in good standing, and the licenses app itself.
    """
    # Skip admin and unauthenticated requests
    if request.path.startswith('/admin/'):
        return {'license_banner': None}
    if not request.user.is_authenticated:
        return {'license_banner': None}

    # Skip the licenses app pages (status + activate) — they surface info directly
    try:
        if request.resolver_match and request.resolver_match.app_name == 'licenses':
            return {'license_banner': None}
    except Exception:
        pass

    lic = License.objects.order_by('-created_at').first()

    if lic is None:
        return {'license_banner': _banner('danger',
            'No active license found. Please activate your Stafforyx HR license.')}

    if lic.is_expired or lic.status == 'expired':
        return {'license_banner': _banner('danger',
            'Your license has expired. Please renew your license.')}

    if lic.status == 'suspended':
        return {'license_banner': _banner('danger',
            'Your license has been suspended. Please contact SYNTRIX PH.')}

    # Lifetime or no expiry — nothing to warn about
    if lic.is_lifetime or lic.valid_until is None:
        return {'license_banner': None}

    days = lic.days_remaining
    if days is not None and 0 <= days <= _WARN_DAYS:
        if days == 0:
            day_text = 'today'
        elif days == 1:
            day_text = 'in 1 day'
        else:
            day_text = f'in {days} days'
        return {'license_banner': _banner('warning',
            f'Your license expires {day_text}. Please renew soon.')}

    return {'license_banner': None}


def _banner(level, message):
    return {'level': level, 'message': message}
