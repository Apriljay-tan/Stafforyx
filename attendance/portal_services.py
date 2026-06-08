"""
WiFi/IP-locked attendance portal helpers.

These functions validate whether an employee's current public IP address
matches any registered AttendanceLocation for their company.

Production note:
    If the app is behind a reverse proxy (nginx, Caddy, AWS ALB, etc.),
    the real client IP arrives in X-Forwarded-For, not REMOTE_ADDR.
    Set TRUSTED_PROXY = True in settings and configure your proxy to set
    X-Forwarded-For correctly before enabling that path here.
    Never trust X-Forwarded-For blindly on a public server - it can be spoofed.
"""

import ipaddress

from django.conf import settings


def get_client_ip(request):
    """
    Return the best-guess client IP address as a string.

    Safe for local development: REMOTE_ADDR is always used unless
    settings.TRUSTED_PROXY is True, in which case proxy headers are used
    in this order:
      1) First IP in X-Forwarded-For
      2) X-Real-IP
      3) REMOTE_ADDR
    """
    if getattr(settings, 'TRUSTED_PROXY', False):
        xff = (request.META.get('HTTP_X_FORWARDED_FOR', '') or '').strip()
        if xff:
            first = xff.split(',')[0].strip()
            if first:
                return first

        x_real_ip = (request.META.get('HTTP_X_REAL_IP', '') or '').strip()
        if x_real_ip:
            return x_real_ip

    return request.META.get('REMOTE_ADDR', '')


def ip_matches_location(ip_str, location):
    """
    Return True if ip_str matches the exact ip_address or falls within
    the cidr_range registered on the given AttendanceLocation.
    """
    if not ip_str:
        return False
    try:
        client_addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return False

    if location.ip_address:
        try:
            if client_addr == ipaddress.ip_address(location.ip_address):
                return True
        except ValueError:
            pass

    if location.cidr_range:
        try:
            network = ipaddress.ip_network(location.cidr_range, strict=False)
            if client_addr in network:
                return True
        except ValueError:
            pass

    return False


def get_authorized_companies_for_employee(employee):
    """
    Return a queryset of Company objects that belong to the same
    owner/admin system as the employee's company.

    "Same system" = any company that shares at least one active
    UserCompanyAccess admin user with the employee's company.  This lets
    an admin who manages multiple branches/companies allow employees to
    clock from any of those locations.

    Superuser accounts are intentionally excluded from the shared-user
    calculation — a superuser having access to all companies must not
    cause every location in the system to be unlocked for an employee.
    """
    from accounts.models import UserCompanyAccess
    from companies.models import Company

    admin_user_ids = list(
        UserCompanyAccess.objects
        .filter(company=employee.company, is_active=True)
        .values_list('user_id', flat=True)
    )
    if not admin_user_ids:
        return Company.objects.filter(pk=employee.company_id)

    authorized_company_ids = (
        UserCompanyAccess.objects
        .filter(user_id__in=admin_user_ids, is_active=True)
        .values_list('company_id', flat=True)
        .distinct()
    )
    return Company.objects.filter(pk__in=authorized_company_ids)


def find_matching_attendance_location(employee, ip_str):
    """
    Return the first active AttendanceLocation whose IP/CIDR matches ip_str,
    or None if no match is found.

    Scoping rules:
      - allow_other_registered_locations=False: only locations under
        employee.company are searched.
      - allow_other_registered_locations=True: locations under all companies
        that share an admin user with employee.company are searched (i.e. the
        same owner/admin system).  Random companies outside that system are
        never included.
    """
    from .models import AttendanceLocation

    if employee.allow_other_registered_locations:
        authorized_companies = get_authorized_companies_for_employee(employee)
        locations = AttendanceLocation.objects.filter(
            company__in=authorized_companies,
            is_active=True,
        ).select_related('company')
    else:
        locations = AttendanceLocation.objects.filter(
            company=employee.company,
            is_active=True,
        ).select_related('company')

    for loc in locations:
        if ip_matches_location(ip_str, loc):
            return loc
    return None


def can_employee_clock_from_request(request, employee):
    """
    Check whether the employee is allowed to clock in/out from this request.

    Returns a dict:
        allowed                          (bool)
        ip                               (str)  - detected client IP
        location                         (AttendanceLocation or None) - matched location
        reason                           (str)  - human-readable explanation when blocked
        locations_checked                (int)  - how many active locations were evaluated
        allow_other_registered_locations (bool) - value of the employee flag
        ip_validation_enabled            (bool) - company-level IP validation switch
        company_require_gps              (bool) - GPS requirement when IP validation is off
        company_require_selfie           (bool) - selfie requirement when IP validation is off
    """
    from .models import AttendanceLocation

    ip = get_client_ip(request)
    allows_cross = bool(getattr(employee, 'allow_other_registered_locations', False))
    company = employee.company
    ip_validation_enabled = bool(getattr(company, 'attendance_ip_validation_enabled', True))
    company_require_gps = bool(getattr(company, 'require_attendance_gps_when_ip_disabled', True))
    company_require_selfie = bool(getattr(company, 'require_attendance_selfie_when_ip_disabled', True))

    # ── IP validation disabled path ──────────────────────────────────────────
    if not ip_validation_enabled:
        return {
            'allowed': True,
            'ip': ip,
            'location': None,
            'reason': '',
            'locations_checked': 0,
            'allow_other_registered_locations': allows_cross,
            'ip_validation_enabled': False,
            'company_require_gps': company_require_gps,
            'company_require_selfie': company_require_selfie,
        }

    # ── Normal IP validation path ────────────────────────────────────────────
    if allows_cross:
        authorized_companies = get_authorized_companies_for_employee(employee)
        locations_qs = AttendanceLocation.objects.filter(
            company__in=authorized_companies,
            is_active=True,
        ).select_related('company')
    else:
        locations_qs = AttendanceLocation.objects.filter(
            company=employee.company,
            is_active=True,
        ).select_related('company')

    locations = list(locations_qs)
    matched = None
    for loc in locations:
        if ip_matches_location(ip, loc):
            matched = loc
            break

    if matched:
        return {
            'allowed': True,
            'ip': ip,
            'location': matched,
            'reason': '',
            'locations_checked': len(locations),
            'allow_other_registered_locations': allows_cross,
            'ip_validation_enabled': True,
            'company_require_gps': False,
            'company_require_selfie': False,
        }

    n = len(locations)
    scope_desc = 'your company or its authorized branches' if allows_cross else 'your company'
    reason = (
        f'Network blocked. Your IP ({ip}) did not match any of the '
        f'{n} active location{"s" if n != 1 else ""} registered for {scope_desc}.'
    )

    return {
        'allowed': False,
        'ip': ip,
        'location': None,
        'reason': reason,
        'locations_checked': n,
        'allow_other_registered_locations': allows_cross,
        'ip_validation_enabled': True,
        'company_require_gps': False,
        'company_require_selfie': False,
    }


def find_open_record(employee, today=None):
    """
    Return the employee's most recent open AttendanceRecord (time_in set,
    time_out missing) from today or yesterday.

    Covers overnight shifts: an employee who clocked in before midnight and
    is still open after midnight is found by the yesterday search.

    Returns None when no open record exists in either day.
    """
    import datetime as _dt
    from .models import AttendanceRecord

    if today is None:
        today = _dt.date.today()
    yesterday = today - _dt.timedelta(days=1)

    return (
        AttendanceRecord.objects
        .filter(
            employee=employee,
            date__in=[today, yesterday],
            time_in__isnull=False,
            time_out__isnull=True,
        )
        .order_by('-date')
        .first()
    )


def is_in_clock_window(t, window_from, window_until):
    """
    Return True if time `t` falls within the [window_from, window_until] window.

    Handles midnight-crossing windows (e.g., 22:00 → 03:00): when
    window_from > window_until the range wraps past midnight.

    Either boundary being None means that side is unbounded (always True).

    IMPORTANT: This utility is for enforcing allowed_clock_in_from /
    allowed_clock_in_until.  Never use it to block a time-OUT operation for
    flexible employees — only time-IN may be restricted by a clock window.
    """
    if window_from is None and window_until is None:
        return True
    if window_from is None:
        return t <= window_until
    if window_until is None:
        return t >= window_from

    t_min = t.hour * 60 + t.minute
    from_min = window_from.hour * 60 + window_from.minute
    until_min = window_until.hour * 60 + window_until.minute

    if from_min <= until_min:
        # Normal window, e.g. 08:00 – 22:00
        return from_min <= t_min <= until_min
    else:
        # Midnight-crossing window, e.g. 22:00 – 03:00
        return t_min >= from_min or t_min <= until_min
