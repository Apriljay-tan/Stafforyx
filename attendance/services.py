"""
Attendance computation helpers.

compute_attendance(record) resolves the employee's schedule for the exact
attendance date and populates derived attendance fields.
"""

from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from .schedule_services import resolve_expected_shift

_60 = Decimal(60)


def _to_min(t):
    """Convert a time object to minutes since midnight."""
    return t.hour * 60 + t.minute


def _minutes_to_hours(minutes):
    """Convert integer minutes to a 2-decimal-place Decimal hours value."""
    return (Decimal(minutes) / _60).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _is_flexible_employee(employee):
    return bool(getattr(employee, 'uses_flexible_attendance_policy', False))


def _flexible_break_minutes(record, employee):
    if record.break_minutes:
        return record.break_minutes
    return employee.default_break_minutes or 0


def _required_minutes(employee):
    return int(
        (Decimal(str(employee.required_daily_hours or 0)) * _60)
        .to_integral_value(rounding=ROUND_HALF_UP)
    )


def _overlap_minutes(start, end, window_start, window_end):
    overlap_start = max(start, window_start)
    overlap_end = min(end, window_end)
    if overlap_end <= overlap_start:
        return 0
    return int((overlap_end - overlap_start).total_seconds() // 60)


def calculate_night_differential_minutes(record, employee=None):
    employee = employee or record.employee
    if not getattr(employee, 'night_differential_enabled', False):
        return 0

    percentage = Decimal(str(getattr(employee, 'night_differential_percentage', 0) or 0))
    if percentage <= 0:
        return 0

    start_time = getattr(employee, 'night_differential_start_time', None)
    end_time = getattr(employee, 'night_differential_end_time', None)
    if not start_time or not end_time or start_time == end_time:
        return 0
    if not record.time_in or not record.time_out:
        return 0

    work_start = datetime.combine(record.date, record.time_in)
    work_end = datetime.combine(record.date, record.time_out)
    if work_end <= work_start:
        work_end += timedelta(days=1)

    minutes = 0
    window_date = work_start.date() - timedelta(days=1)
    final_window_date = work_end.date()

    while window_date <= final_window_date:
        window_start = datetime.combine(window_date, start_time)
        window_end = datetime.combine(window_date, end_time)
        if window_end <= window_start:
            window_end += timedelta(days=1)
        minutes += _overlap_minutes(work_start, work_end, window_start, window_end)
        window_date += timedelta(days=1)

    return minutes


def compute_attendance(record):
    """
    Compute late, undertime, overtime, total work minutes, and computed status.

    Fixed employees keep the existing resolved-shift behavior. Flexible
    employees use employee-level required hours and day-off settings instead of
    a fixed start/end time.
    """
    shift = resolve_expected_shift(record.employee, record.date)

    late_min = 0
    undertime_min = 0
    overtime_min = 0
    total_work_min = 0
    computed = ''

    if not shift['scheduled']:
        if shift['is_rest_day']:
            if record.time_in and record.time_out:
                time_in_min = _to_min(record.time_in)
                time_out_min = _to_min(record.time_out)
                if time_out_min < time_in_min:
                    time_out_min += 24 * 60
                total_work_min = max(
                    0,
                    time_out_min - time_in_min - (record.break_minutes or 0),
                )
            computed = 'rest_day'
        else:
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
        employee = record.employee
        if _is_flexible_employee(employee):
            if shift.get('is_rest_day') and not record.time_in:
                computed = 'rest_day'
            elif not record.time_in:
                computed = 'absent'
            elif not record.time_out:
                computed = 'incomplete'
            else:
                time_in_min = _to_min(record.time_in)
                time_out_min = _to_min(record.time_out)
                if time_out_min <= time_in_min:
                    time_out_min += 24 * 60

                break_min = _flexible_break_minutes(record, employee)
                total_work_min = max(0, time_out_min - time_in_min - break_min)

                if shift.get('is_rest_day'):
                    computed = 'rest_day'
                else:
                    required_min = _required_minutes(employee)
                    overtime_grace_min = employee.flexible_overtime_grace_minutes or 0
                    undertime_min = max(0, required_min - total_work_min)
                    overtime_min = max(
                        0,
                        total_work_min - required_min - overtime_grace_min,
                    )
                    computed = 'undertime' if undertime_min > 0 else 'present'

        elif not record.time_in:
            computed = 'absent'
        else:
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

                expected_min = max(
                    0,
                    sched_end_min - sched_start_min - shift['break_minutes'],
                )
                undertime_min = max(0, expected_min - total_work_min)

                ot_start_min = sched_end_min + (shift['overtime_after_minutes'] or 0)
                overtime_min = max(0, time_out_min - ot_start_min)

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

    night_diff_min = calculate_night_differential_minutes(record, record.employee)

    record.late_minutes = late_min
    record.undertime_minutes = undertime_min
    record.overtime_minutes = overtime_min
    record.total_work_minutes = total_work_min
    record.night_differential_minutes = night_diff_min
    record.total_hours = _minutes_to_hours(total_work_min)
    record.overtime_hours = _minutes_to_hours(overtime_min)
    record.computed_status = computed
    record.save(update_fields=[
        'late_minutes', 'undertime_minutes', 'overtime_minutes',
        'total_work_minutes', 'night_differential_minutes', 'total_hours',
        'overtime_hours', 'computed_status',
    ])
