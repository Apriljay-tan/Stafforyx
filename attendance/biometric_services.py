"""
Biometric attendance foundation helpers.

These functions form the data layer for future cloud biometric sync.
No attendance records are auto-created here — that will be a separate
processing step once the sync pipeline is stable.
"""

from django.utils import timezone

from employees.models import Employee
from .models import BiometricLog


def match_employee_for_biometric_log(company, biometric_user_id):
    """
    Return the Employee whose biometric_user_id matches within the given company,
    or None if no match is found.

    Matching is always scoped to the company so the same device ID number used
    in two different companies never cross-maps to the wrong employee.
    """
    if not biometric_user_id:
        return None
    try:
        return Employee.objects.get(company=company, biometric_user_id=biometric_user_id)
    except Employee.DoesNotExist:
        return None


def create_biometric_log(
    company,
    punch_time,
    biometric_user_id,
    device=None,
    punch_type='unknown',
    raw_status_code='',
    raw_payload=None,
):
    """
    Persist a raw log entry received from a biometric device.

    Attempts to resolve the employee via company + biometric_user_id.
    If no match is found the log is still saved with employee=None so
    the raw data is never lost.

    Returns the created BiometricLog instance.
    """
    employee = match_employee_for_biometric_log(company, biometric_user_id)
    return BiometricLog.objects.create(
        company=company,
        device=device,
        employee=employee,
        biometric_user_id=biometric_user_id,
        punch_time=punch_time,
        punch_type=punch_type,
        raw_status_code=raw_status_code,
        raw_payload=raw_payload if raw_payload is not None else {},
    )


def mark_log_processed(log, attendance_record=None, error_message=''):
    """
    Mark a BiometricLog as processed (or failed).

    attendance_record: the AttendanceRecord that was created/updated from this log.
    error_message: non-empty string if processing failed.
    """
    log.processed = True
    log.processed_at = timezone.now()
    if attendance_record is not None:
        log.attendance_record = attendance_record
    if error_message:
        log.error_message = error_message
    log.save(update_fields=['processed', 'processed_at', 'attendance_record', 'error_message'])
