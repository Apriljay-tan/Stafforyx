import hashlib
import secrets
from dataclasses import dataclass

from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import AttendanceQRScanLog, AttendanceQRToken
from .portal_services import get_authorized_companies_for_employee, get_client_ip


QR_RATE_LIMIT_ATTEMPTS = 20
QR_RATE_LIMIT_WINDOW_SECONDS = 60


@dataclass(frozen=True)
class IssuedQRToken:
    token: AttendanceQRToken
    raw_token: str


@dataclass(frozen=True)
class QRValidationResult:
    allowed: bool
    result: str
    message: str
    token: AttendanceQRToken | None = None
    company: object | None = None
    attendance_location: object | None = None
    kiosk_device: object | None = None
    scan_log: AttendanceQRScanLog | None = None


def hash_qr_token(raw_token):
    return hashlib.sha256(raw_token.encode('utf-8')).hexdigest()


def _bounded_int(value, *, default, minimum, maximum=None):
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    number = max(number, minimum)
    if maximum is not None:
        number = min(number, maximum)
    return number


def _token_lifetime_seconds(company):
    configured = getattr(company, 'attendance_qr_token_lifetime_seconds', 60)
    return _bounded_int(configured, default=60, minimum=30, maximum=300)


def _token_retention_days(company):
    configured = getattr(company, 'attendance_qr_token_retention_days', 1)
    return _bounded_int(configured, default=1, minimum=1)


def _cleanup_expired_tokens_for_kiosk(kiosk_device, now):
    company = kiosk_device.company
    if not getattr(company, 'attendance_auto_delete_qr_tokens', True):
        return 0

    cutoff = now - timezone.timedelta(days=_token_retention_days(company))
    deleted_count, breakdown = (
        AttendanceQRToken.objects
        .filter(kiosk_device=kiosk_device, expires_at__lt=cutoff)
        .delete()
    )
    return breakdown.get('attendance.AttendanceQRToken', 0) or deleted_count


def create_qr_token(kiosk_device, now=None):
    now = now or timezone.now()
    lifetime = _token_lifetime_seconds(kiosk_device.company)
    expires_at = now + timezone.timedelta(seconds=lifetime)

    _cleanup_expired_tokens_for_kiosk(kiosk_device, now)

    for _attempt in range(3):
        raw_token = secrets.token_urlsafe(32)
        token_hash = hash_qr_token(raw_token)
        try:
            with transaction.atomic():
                token = AttendanceQRToken.objects.create(
                    kiosk_device=kiosk_device,
                    attendance_location=kiosk_device.attendance_location,
                    company=kiosk_device.company,
                    token_hash=token_hash,
                    issued_at=now,
                    expires_at=expires_at,
                    is_active=True,
                )
                AttendanceQRToken.objects.filter(
                    kiosk_device=kiosk_device,
                    is_active=True,
                ).exclude(pk=token.pk).update(is_active=False)
            return IssuedQRToken(token=token, raw_token=raw_token)
        except IntegrityError:
            continue

    raise RuntimeError('Could not issue a unique attendance QR token.')


def _employee_can_use_token_company(employee, company):
    if company.pk == employee.company_id:
        return True
    if not getattr(employee, 'allow_other_registered_locations', False):
        return False
    return get_authorized_companies_for_employee(employee).filter(pk=company.pk).exists()


def _rate_limited(employee, ip):
    if employee is None or not ip:
        return False
    key = f'attendance:qr-validation:{employee.pk}:{ip}'
    attempts = cache.get(key, 0) + 1
    cache.set(key, attempts, QR_RATE_LIMIT_WINDOW_SECONDS)
    return attempts > QR_RATE_LIMIT_ATTEMPTS


def _create_scan_log(
    *,
    employee,
    token_hash,
    result,
    action,
    request=None,
    token=None,
    gps_latitude=None,
    gps_longitude=None,
    gps_accuracy=None,
):
    ip = get_client_ip(request) if request is not None else ''
    user_agent = (request.META.get('HTTP_USER_AGENT', '') if request is not None else '')[:500]
    company = token.company if token is not None else getattr(employee, 'company', None)
    attendance_location = token.attendance_location if token is not None else None
    kiosk_device = token.kiosk_device if token is not None else None
    return AttendanceQRScanLog.objects.create(
        employee=employee,
        company=company,
        attendance_location=attendance_location,
        kiosk_device=kiosk_device,
        qr_token=token,
        token_hash=token_hash,
        action=action,
        result=result,
        ip_address=ip or None,
        gps_latitude=gps_latitude,
        gps_longitude=gps_longitude,
        gps_accuracy=gps_accuracy,
        user_agent=user_agent,
    )


def validate_qr_token_for_employee(
    employee,
    raw_token,
    *,
    action='validate',
    request=None,
    gps_latitude=None,
    gps_longitude=None,
    gps_accuracy=None,
    log_attempt=True,
):
    raw_token = (raw_token or '').strip()
    ip = get_client_ip(request) if request is not None else ''

    if _rate_limited(employee, ip):
        scan_log = None
        if log_attempt:
            scan_log = _create_scan_log(
                employee=employee,
                token_hash=hash_qr_token(raw_token) if raw_token else '',
                result='rate_limited',
                action=action,
                request=request,
                gps_latitude=gps_latitude,
                gps_longitude=gps_longitude,
                gps_accuracy=gps_accuracy,
            )
        return QRValidationResult(
            allowed=False,
            result='rate_limited',
            message='Too many QR validation attempts. Please wait and try again.',
            scan_log=scan_log,
        )

    if not raw_token:
        scan_log = None
        if log_attempt:
            scan_log = _create_scan_log(
                employee=employee,
                token_hash='',
                result='missing',
                action=action,
                request=request,
                gps_latitude=gps_latitude,
                gps_longitude=gps_longitude,
                gps_accuracy=gps_accuracy,
            )
        return QRValidationResult(
            allowed=False,
            result='missing',
            message='A live branch QR code is required before clocking.',
            scan_log=scan_log,
        )

    token_hash = hash_qr_token(raw_token)
    token = (
        AttendanceQRToken.objects
        .select_related('company', 'attendance_location', 'kiosk_device')
        .filter(token_hash=token_hash)
        .first()
    )

    if token is None or not token.is_active:
        scan_log = None
        if log_attempt:
            scan_log = _create_scan_log(
                employee=employee,
                token_hash=token_hash,
                result='invalid',
                action=action,
                request=request,
                gps_latitude=gps_latitude,
                gps_longitude=gps_longitude,
                gps_accuracy=gps_accuracy,
            )
        return QRValidationResult(
            allowed=False,
            result='invalid',
            message='The branch QR code is invalid. Please scan the live QR again.',
            scan_log=scan_log,
        )

    now = timezone.now()
    if token.expires_at <= now:
        scan_log = None
        if log_attempt:
            scan_log = _create_scan_log(
                employee=employee,
                token_hash=token_hash,
                result='expired',
                action=action,
                request=request,
                token=token,
                gps_latitude=gps_latitude,
                gps_longitude=gps_longitude,
                gps_accuracy=gps_accuracy,
            )
        return QRValidationResult(
            allowed=False,
            result='expired',
            message='The branch QR code has expired. Please scan the latest QR.',
            token=token,
            company=token.company,
            attendance_location=token.attendance_location,
            kiosk_device=token.kiosk_device,
            scan_log=scan_log,
        )

    if not token.kiosk_device.is_active:
        result = 'inactive_device'
        message = 'This QR kiosk device is inactive. Please contact HR.'
    elif not token.attendance_location.is_active:
        result = 'inactive_location'
        message = 'This attendance location is inactive. Please contact HR.'
    elif (
        token.kiosk_device.company_id != token.company_id
        or token.attendance_location.company_id != token.company_id
        or token.kiosk_device.attendance_location_id != token.attendance_location_id
    ):
        result = 'invalid'
        message = 'The branch QR code is invalid. Please scan the live QR again.'
    elif not _employee_can_use_token_company(employee, token.company):
        result = 'unauthorized'
        message = 'This branch QR code is not authorized for your employee record.'
    else:
        result = 'success'
        message = 'Branch QR validated.'

    scan_log = None
    if log_attempt:
        scan_log = _create_scan_log(
            employee=employee,
            token_hash=token_hash,
            result=result,
            action=action,
            request=request,
            token=token,
            gps_latitude=gps_latitude,
            gps_longitude=gps_longitude,
            gps_accuracy=gps_accuracy,
        )

    return QRValidationResult(
        allowed=result == 'success',
        result=result,
        message=message,
        token=token,
        company=token.company,
        attendance_location=token.attendance_location,
        kiosk_device=token.kiosk_device,
        scan_log=scan_log,
    )
