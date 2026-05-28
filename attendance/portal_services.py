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


def find_matching_attendance_location(employee, ip_str):
    """
    Return the first active AttendanceLocation for the employee's company
    whose IP/CIDR matches ip_str, or None if no match is found.
    """
    from .models import AttendanceLocation

    locations = AttendanceLocation.objects.filter(
        company=employee.company,
        is_active=True,
    )
    for loc in locations:
        if ip_matches_location(ip_str, loc):
            return loc
    return None


def can_employee_clock_from_request(request, employee):
    """
    Check whether the employee is allowed to clock in/out from this request.

    Returns a dict:
        allowed  (bool)
        ip       (str) - detected client IP
        location (AttendanceLocation or None) - matched location
        reason   (str) - human-readable explanation when blocked
    """
    ip = get_client_ip(request)
    location = find_matching_attendance_location(employee, ip)

    if location:
        return {
            'allowed': True,
            'ip': ip,
            'location': location,
            'reason': '',
        }

    return {
        'allowed': False,
        'ip': ip,
        'location': None,
        'reason': (
            'Attendance is blocked. You are not connected to an approved '
            'company network. Contact your HR admin if you believe this is an error.'
        ),
    }
