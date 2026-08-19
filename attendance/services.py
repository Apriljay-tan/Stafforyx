"""
Attendance computation helpers.

compute_attendance(record) resolves the employee's schedule for the exact
attendance date and populates derived attendance fields.
"""

from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from companies.models import OVERTIME_COUNTING_RULE_EXACT
from .schedule_services import resolve_expected_shift

_60 = Decimal(60)

# Block size in minutes for each overtime counting rule value.
_OVERTIME_BLOCK_MINUTES = {'30': 30, '60': 60, '120': 120}


def resolve_overtime_rule(employee):
    """
    Resolve the effective overtime counting rule for an employee.

    Priority: employee override → employee's company default → 'exact'.
    A blank employee override means "inherit from company".
    """
    override = (getattr(employee, 'overtime_counting_rule', '') or '').strip()
    if override:
        return override
    company = getattr(employee, 'company', None)
    company_rule = (getattr(company, 'default_overtime_counting_rule', '') or '').strip()
    return company_rule or OVERTIME_COUNTING_RULE_EXACT


def apply_overtime_rule(actual_minutes, rule):
    """
    Count overtime minutes by completed blocks, flooring DOWN.

    'exact' (or blank/unknown) returns the actual minutes unchanged. Block rules
    return the largest multiple of the block size that does not exceed
    ``actual_minutes`` (e.g. 59 under the '30' rule → 30; 29 → 0).
    """
    block = _OVERTIME_BLOCK_MINUTES.get(rule)
    if not block:
        return actual_minutes
    return (actual_minutes // block) * block


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


def _overtime_grace_threshold_minutes(employee):
    """Minimum detected OT minutes before payable OT accrues (request_required)."""
    return int(getattr(employee, 'flexible_overtime_grace_minutes', 0) or 0)


def _approved_overtime_minutes_for_date(employee, date):
    from overtime.services import build_overtime_approval_index

    approval_index = build_overtime_approval_index(
        employee.company, [employee], date, date,
    )
    return approval_index.get((employee.id, date), 0)


def _resolve_payable_raw_overtime_minutes(employee, date, actual_overtime_min):
    """
    Map detected overtime minutes to payable raw minutes before the counting rule.

    automatic: pay all detected overtime.
    no_ot: never pay overtime.
    request_required: pay only with an approved request, after the grace
    threshold, capped at approved minutes.
    """
    policy = getattr(employee, 'overtime_mode', None) or getattr(
        employee, 'overtime_policy', 'no_ot',
    )

    if policy in ('no_ot', 'not_allowed'):
        return 0
    if policy == 'automatic':
        return actual_overtime_min or 0

    approved_min = _approved_overtime_minutes_for_date(employee, date)
    if approved_min <= 0:
        return 0

    actual = actual_overtime_min or 0
    if actual <= _overtime_grace_threshold_minutes(employee):
        return 0

    return min(actual, approved_min)


def _hours_to_overtime_minutes(hours):
    return int(
        (Decimal(str(hours or 0)) * _60).to_integral_value(rounding=ROUND_HALF_UP)
    )


def _finalize_computed_status(computed, counted_overtime_min, late_min, undertime_min):
    """
    Persist a computed status that reflects payable overtime, not raw detection.

    Overtime status is only stored when counted/payable overtime is positive.
    """
    if (counted_overtime_min or 0) > 0:
        return 'overtime'
    if computed == 'overtime':
        if undertime_min > 0:
            return 'undertime'
        if late_min > 0:
            return 'late'
        return 'present'
    return computed


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


def compute_attendance(record, overtime_override=None):
    """
    Compute late, undertime, overtime, total work minutes, and computed status.

    Fixed employees keep the existing resolved-shift behavior. Flexible
    employees use employee-level required hours and day-off settings instead of
    a fixed start/end time.

    When ``overtime_override`` is set (admin manually edited overtime_hours on
    the attendance form), payable overtime fields are taken from that value
    instead of being auto-derived from clock times and policy.
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
                expected_min = max(
                    0,
                    sched_end_min - sched_start_min - shift['break_minutes'],
                )

                ot_start_min = sched_end_min + (shift['overtime_after_minutes'] or 0)
                overtime_min = max(0, time_out_min - ot_start_min)

                regular_start_min = max(time_in_min, sched_start_min)
                regular_end_min = min(time_out_min, sched_end_min)
                regular_span_min = max(0, regular_end_min - regular_start_min)
                regular_work_min = max(0, regular_span_min - break_min)
                total_work_min = regular_work_min + overtime_min
                undertime_min = max(0, expected_min - regular_work_min)

                if overtime_min > 0:
                    undertime_min = 0

                half_day_cutoff = shift.get('half_day_cutoff_time')
                is_half_day = False
                if half_day_cutoff is not None:
                    cutoff_min = _to_min(half_day_cutoff)
                    if is_overnight and cutoff_min <= sched_start_min:
                        cutoff_min += 24 * 60
                    if sched_start_min < cutoff_min <= sched_end_min and time_out_min <= cutoff_min:
                        is_half_day = True
                        total_work_min = max(0, time_out_min - regular_start_min)
                        undertime_min = max(0, cutoff_min - max(time_out_min, regular_start_min))
                        overtime_min = 0

                if is_half_day:
                    computed = 'half_day'
                elif overtime_min > 0:
                    computed = 'overtime'
                elif undertime_min > 0:
                    computed = 'undertime'
                elif late_min > 0:
                    computed = 'late'
                else:
                    computed = 'present'

    night_diff_min = calculate_night_differential_minutes(record, record.employee)

    # overtime_min is the raw detected overtime. Preserve it as the audit value
    # and apply policy + counting rule to derive payable overtime fields.
    actual_overtime_min = overtime_min
    if overtime_override is not None:
        counted_overtime_min = _hours_to_overtime_minutes(overtime_override)
        overtime_hours = Decimal(str(overtime_override)).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP,
        )
    else:
        payable_raw_min = _resolve_payable_raw_overtime_minutes(
            record.employee, record.date, actual_overtime_min,
        )
        overtime_rule = resolve_overtime_rule(record.employee)
        counted_overtime_min = apply_overtime_rule(payable_raw_min, overtime_rule)
        overtime_hours = _minutes_to_hours(counted_overtime_min)

    computed = _finalize_computed_status(
        computed, counted_overtime_min, late_min, undertime_min,
    )

    record.late_minutes = late_min
    record.undertime_minutes = undertime_min
    record.actual_overtime_minutes = actual_overtime_min
    record.overtime_minutes = counted_overtime_min
    record.total_work_minutes = total_work_min
    record.night_differential_minutes = night_diff_min
    record.total_hours = _minutes_to_hours(total_work_min)
    record.overtime_hours = overtime_hours
    record.computed_status = computed
    record.save(update_fields=[
        'late_minutes', 'undertime_minutes', 'actual_overtime_minutes',
        'overtime_minutes', 'total_work_minutes', 'night_differential_minutes',
        'total_hours', 'overtime_hours', 'computed_status',
    ])
