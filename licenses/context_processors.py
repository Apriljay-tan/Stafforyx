from datetime import date as _date
from .models import License

_WARN_DAYS = 7

# Reasons map to human-readable banner messages
_REASON_MESSAGES = {
    'no_license':      'No active license found. Please activate your Stafforyx HR license.',
    'no_key':          'No license key found. Please re-activate your Stafforyx HR license.',
    'bad_sig':         'License signature is invalid — this license was not issued by SYNTRIX PH. '
                       'Please re-activate with a valid license key.',
    'machine_mismatch':'License is bound to a different machine. '
                       'Please request a license for this Machine ID.',
    'expired':         'Your license has expired. Please renew your license.',
}


# ── Core verified state ──────────────────────────────────────────────────────

def get_license_state():
    """
    Determine license validity by cryptographically verifying the stored key.
    Never trusts DB status, plan, or date fields — those can be edited in admin.
    Only the signed payload is authoritative.

    Returns a dict:
      lic          — License DB object (or None)
      valid        — True only when signature OK + not expired + machine matches
      expired      — True when signature OK but dates are past
      reason       — one of: ok | no_license | no_key | bad_sig |
                              machine_mismatch | expired
      plan         — from signed payload (or '')
      days_remaining — int or None
      is_lifetime  — bool
    """
    from .license_verifier import verify_signed_license
    from .machine import get_machine_id

    lic = License.objects.order_by('-created_at').first()

    if lic is None:
        return _state(None, valid=False, expired=False, reason='no_license')

    if not (lic.license_key or '').strip():
        return _state(lic, valid=False, expired=False, reason='no_key')

    ok, result = verify_signed_license(lic.license_key)
    if not ok:
        return _state(lic, valid=False, expired=False, reason='bad_sig')

    payload = result
    plan = payload.get('plan', '')
    valid_until_str = (payload.get('valid_until') or '').strip()

    # max_employees from signed payload — 0 means use safest behaviour (block adds)
    raw_max = payload.get('max_employees')
    max_employees = raw_max if isinstance(raw_max, int) and raw_max > 0 else 0

    # Machine ID — validated from signed payload, not from DB
    payload_mid = (payload.get('machine_id') or '').strip()
    if payload_mid and payload_mid != get_machine_id():
        return _state(lic, valid=False, expired=False, reason='machine_mismatch',
                      plan=plan, max_employees=max_employees)

    is_lifetime = (plan == 'lifetime')
    if is_lifetime or not valid_until_str:
        return _state(lic, valid=True, expired=False, reason='ok',
                      plan=plan, days_remaining=None, is_lifetime=True,
                      max_employees=max_employees)

    try:
        valid_until_date = _date.fromisoformat(valid_until_str)
        days = (valid_until_date - _date.today()).days
        expired = valid_until_date < _date.today()
    except ValueError:
        expired = False
        days = None

    return _state(lic, valid=not expired, expired=expired,
                  reason='expired' if expired else 'ok',
                  plan=plan, days_remaining=days, is_lifetime=False,
                  max_employees=max_employees)


def _state(lic, valid, expired, reason, plan='', days_remaining=None,
           is_lifetime=False, max_employees=0):
    return {
        'lic':            lic,
        'valid':          valid,
        'expired':        expired,
        'reason':         reason,
        'plan':           plan,
        'days_remaining': days_remaining,
        'is_lifetime':    is_lifetime,
        'max_employees':  max_employees,  # from signed payload; 0 = no valid limit
    }


# ── Public helpers used by middleware and context processor ──────────────────

def is_license_active():
    """
    Return True only when the license has a valid, unexpired, verified signature.
    Used by LicenseReadOnlyMiddleware — imported from here so both share one code path.
    """
    return get_license_state()['valid']


# ── Template context processor ───────────────────────────────────────────────

def license_banner(request):
    """
    Inject `license_banner`, `license_read_only`, and `clock_rollback` into every
    template rendered by base.html.  All validity decisions go through
    get_license_state() — the DB status/date fields are never trusted on their own.
    """
    _clear = {'license_banner': None, 'license_read_only': False, 'clock_rollback': False}

    # clock_rollback is set on request by LicenseReadOnlyMiddleware; fall back to False.
    clock_rollback = getattr(request, '_clock_rollback', False)

    if request.path.startswith('/admin/'):
        return _clear
    if not request.user.is_authenticated:
        return _clear
    try:
        if request.resolver_match and request.resolver_match.app_name == 'licenses':
            return {**_clear, 'clock_rollback': clock_rollback}
    except Exception:
        pass

    s = get_license_state()
    reason = s['reason']
    days   = s['days_remaining']

    if reason == 'ok':
        if s['is_lifetime'] or days is None or days > _WARN_DAYS:
            return {**_clear, 'clock_rollback': clock_rollback}
        # Expiring soon — warn but keep editing enabled
        day_text = ('today' if days == 0 else
                    'in 1 day' if days == 1 else
                    f'in {days} days')
        return {
            'license_banner': _banner('warning',
                f'Your license expires {day_text}. Please renew soon.'),
            'license_read_only': False,
            'clock_rollback': clock_rollback,
        }

    # All other reasons → danger banner + read-only
    msg = _REASON_MESSAGES.get(
        reason,
        'License is inactive. Please activate your Stafforyx HR license.',
    )
    return {
        'license_banner': _banner('danger', msg),
        'license_read_only': True,
        'clock_rollback': clock_rollback,
    }


def _banner(level, message):
    return {'level': level, 'message': message}
