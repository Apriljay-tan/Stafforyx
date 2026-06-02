"""
Attendance computation helpers.

compute_attendance(record) — resolves the employee's schedule for the exact
attendance date (via schedule_services.resolve_expected_shift) and populates
all derived fields on the AttendanceRecord, then saves them.

Schedule priority (handled inside resolve_expected_shift):
  1. EmployeeDailySchedule for that employee + date
  2. Employee.work_schedule (legacy WorkSchedule with weekday flags)
  3. No schedule
"""

from decimal import Decimal, ROUND_HALF_UP

from .schedule_services import resolve_expected_shift

_60 = Decimal(60)


def _to_min(t):
    """Convert a time object to minutes since midnight."""
    return t.hour * 60 + t.minute


def _minutes_to_hours(minutes):
    """Convert integer minutes to a 2-decimal-place Decimal hours value."""
    return (Decimal(minutes) / _60).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def compute_attendance(record):
    """
    Compute late_minutes, undertime_minutes, overtime_minutes,
    total_work_minutes, and computed_status for a single AttendanceRecord,
    then save those derived fields.

    The expected shift is resolved for the record's exact date, so rotating
    shifts and date-specific overrides are handled automatically.

    Rules:
    - Rest day (per schedule) → rest_day status; work minutes counted if clocked in.
    - No schedule → no_schedule / incomplete / present depending on time fields.
    - Missing time_in on scheduled workday → absent.
    - Missing time_out on scheduled workday → incomplete.
    - Overnight shift: time_out < time_in → add 24 h to time_out before arithmetic.
    - Overtime cancels undertime (employee stayed late, so undertime is 0).
    """
    shift = resolve_expected_shift(record.employee, record.date)

    late_min = 0
    undertime_min = 0
    overtime_min = 0
    total_work_min = 0
    computed = ''

    if not shift['scheduled']:
        # ── Rest day or no schedule ────────────────────────────────────────────
        if shift['is_rest_day']:
            if record.time_in and record.time_out:
                time_in_min = _to_min(record.time_in)
                time_out_min = _to_min(record.time_out)
                # Handle wrap-around (e.g. rest-day overnight work)
                if time_out_min < time_in_min:
                    time_out_min += 24 * 60
                total_work_min = max(
                    0,
                    time_out_min - time_in_min - (record.break_minutes or 0),
                )
            computed = 'rest_day'
        else:
            # No schedule assigned
            if record.time_in and not record.time_out:
                computed = 'incomplete'
            elif record.time_in and record.time_out:
                total_work_min = max(
                    0,
                    _to_min(record.time_out) - _to_min(record.time_in)
                    - (record.break_minutes or 0),
                )
                computed = 'present'
            else:
                computed = 'no_schedule'

    else:
        # ── Scheduled workday ─────────────────────────────────────────────────
        if not record.time_in:
            computed = 'absent'
        else:
            employee = record.employee
            if getattr(employee, 'flexible_schedule_enabled', False):
                # ── Flexible schedule (additive, guarded) ─────────────────────
                # Never late for starting later within the allowed window.
                late_min = 0
                if not record.time_out:
                    computed = 'incomplete'
                else:
                    time_in_min = _to_min(record.time_in)
                    time_out_min = _to_min(record.time_out)
                    if shift.get('is_overnight', False) and time_out_min <= time_in_min:
                        time_out_min += 24 * 60
                    break_min = (
                        record.break_minutes
                        if record.break_minutes is not None
                        else (employee.default_break_minutes or 0)
                    )
                    total_work_min = max(0, time_out_min - time_in_min - break_min)
                    required_min = int(
                        (Decimal(str(employee.required_daily_hours or 0)) * _60)
                        .to_integral_value(rounding=ROUND_HALF_UP)
                    )
                    undertime_min = max(0, required_min - total_work_min)
                    overtime_min = max(0, total_work_min - required_min)
                    if overtime_min > 0:
                        undertime_min = 0
                        computed = 'overtime'
                    elif undertime_min > 0:
                        computed = 'undertime'
                    else:
                        computed = 'present'
            else:
                # ── Fixed shift (UNCHANGED) ───────────────────────────────────
                sched_start_min = _to_min(shift['start_time'])
                grace = shift['grace_minutes'] or 0
                time_in_min = _to_min(record.time_in)
                late_min = max(0, time_in_min - (sched_start_min + grace))

                if not record.time_out:
                    computed = 'incomplete'
                else:
                    time_out_min = _to_min(record.time_out)
                    sched_end_min = _to_min(shift['end_time'])
                    is_overnight = shift.get('is_overnight', False)

                    # Overnight: adjust both ends to be continuous minutes from midnight
                    if is_overnight:
                        if sched_end_min <= sched_start_min:
                            sched_end_min += 24 * 60
                        if time_out_min <= time_in_min:
                            time_out_min += 24 * 60

                    break_min = (
                        record.break_minutes
                        if record.break_minutes is not None
                        else shift['break_minutes']
                    )
                    total_work_min = max(0, time_out_min - time_in_min - break_min)

                    # Expected minutes = scheduled span minus break
                    expected_min = max(0, sched_end_min - sched_start_min - shift['break_minutes'])
                    undertime_min = max(0, expected_min - total_work_min)

                    ot_start_min = sched_end_min + (shift['overtime_after_minutes'] or 0)
                    overtime_min = max(0, time_out_min - ot_start_min)

                    # Overtime cancels undertime
                    if overtime_min > 0:
                        undertime_min = 0

                    if overtime_min > 0:
                        computed = 'overtime'
                    elif undertime_min > 0:
                        computed = 'undertime'
                    elif late_min > 0:
                        computed = 'late'
                    else:
                        computed = 'present'

    record.late_minutes = late_min
    record.undertime_minutes = undertime_min
    record.overtime_minutes = overtime_min
    record.total_work_minutes = total_work_min
    record.total_hours = _minutes_to_hours(total_work_min)
    record.overtime_hours = _minutes_to_hours(overtime_min)
    record.computed_status = computed
    record.save(update_fields=[
        'late_minutes', 'undertime_minutes', 'overtime_minutes',
        'total_work_minutes', 'total_hours', 'overtime_hours', 'computed_status',
    ])
