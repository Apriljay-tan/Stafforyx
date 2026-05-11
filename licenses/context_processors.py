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
    Inject `license_banner` and `license_read_only` into every template context.
    license_read_only=True when the license is absent, expired, or suspended.
    """
    _inactive = {'license_banner': None, 'license_read_only': False}

    if request.path.startswith('/admin/'):
        return _inactive
    if not request.user.is_authenticated:
        return _inactive

    try:
        if request.resolver_match and request.resolver_match.app_name == 'licenses':
            return _inactive
    except Exception:
        pass

    lic = License.objects.order_by('-created_at').first()

    if lic is None:
        return {
            'license_banner': _banner('danger',
                'No active license found. Please activate your Stafforyx HR license.'),
            'license_read_only': True,
        }

    if lic.is_expired or lic.status == 'expired':
        return {
            'license_banner': _banner('danger',
                'Your license has expired. Please renew your license.'),
            'license_read_only': True,
        }

    if lic.status == 'suspended':
        return {
            'license_banner': _banner('danger',
                'Your license has been suspended. Please contact SYNTRIX PH.'),
            'license_read_only': True,
        }

    # Lifetime or no expiry — fully active
    if lic.is_lifetime or lic.valid_until is None:
        return {'license_banner': None, 'license_read_only': False}

    days = lic.days_remaining
    if days is not None and 0 <= days <= _WARN_DAYS:
        if days == 0:
            day_text = 'today'
        elif days == 1:
            day_text = 'in 1 day'
        else:
            day_text = f'in {days} days'
        return {
            'license_banner': _banner('warning',
                f'Your license expires {day_text}. Please renew soon.'),
            'license_read_only': False,
        }

    return {'license_banner': None, 'license_read_only': False}


def _banner(level, message):
    return {'level': level, 'message': message}
