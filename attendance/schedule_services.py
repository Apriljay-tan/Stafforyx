"""
Schedule resolver — determines the expected shift for an employee on a given date.

Priority:
  1. EmployeeDailySchedule for that employee + date (date-specific override or roster)
  2. Employee.work_schedule (WorkSchedule — legacy default with weekday flags)
  3. No schedule

The return value is always a normalized dict so attendance computation and the
portal view can use the same interface regardless of which source was resolved.
"""

import datetime

_DAY_FIELDS = [
    'work_monday', 'work_tuesday', 'work_wednesday', 'work_thursday',
    'work_friday', 'work_saturday', 'work_sunday',
]

_UNSCHEDULED = {
    'scheduled': False,
    'is_rest_day': False,
    'start_time': None,
    'end_time': None,
    'is_overnight': False,
    'break_minutes': 0,
    'half_day_cutoff_time': None,
    'grace_minutes': 0,
    'overtime_after_minutes': 0,
    'allow_early_clock_in_minutes': 30,
    'source': 'none',
    'daily_schedule': None,
    'shift_template': None,
    'reason': 'No schedule assigned for this date.',
}


def _is_flexible_employee(employee):
    return bool(getattr(employee, 'uses_flexible_attendance_policy', False))


def _flexible_shift(employee, date):
    is_day_off = employee.is_flexible_day_off(date)
    return {
        'scheduled': True,
        'is_rest_day': is_day_off,
        'start_time': None,
        'end_time': None,
        'is_overnight': False,
        'break_minutes': employee.default_break_minutes or 0,
        'half_day_cutoff_time': None,
        'grace_minutes': 0,
        'overtime_after_minutes': employee.flexible_overtime_grace_minutes or 0,
        'allow_early_clock_in_minutes': 0,
        'source': 'flexible_policy',
        'daily_schedule': None,
        'shift_template': None,
        'reason': 'Flexible day-off.' if is_day_off else '',
    }


def get_employee_schedule_for_date(employee, date):
    """Return the EmployeeDailySchedule for employee+date, or None."""
    from .models import EmployeeDailySchedule
    try:
        return EmployeeDailySchedule.objects.select_related(
            'shift_template'
        ).get(employee=employee, schedule_date=date)
    except EmployeeDailySchedule.DoesNotExist:
        return None


def resolve_expected_shift(employee, date):
    """
    Return a normalized dict describing the expected shift for employee on date.

    Dict keys:
        scheduled               bool — True if employee is expected to work
        is_rest_day             bool
        start_time              datetime.time or None
        end_time                datetime.time or None
        is_overnight            bool — True if shift crosses midnight
        break_minutes           int
        half_day_cutoff_time    datetime.time or None
        grace_minutes           int
        overtime_after_minutes  int — minutes after end_time before OT counts
        allow_early_clock_in_minutes  int
        source                  'daily_schedule' | 'work_schedule' | 'none'
        daily_schedule          EmployeeDailySchedule or None
        shift_template          ShiftTemplate or None
        reason                  str — human-readable, empty when scheduled
    """

    # ── Priority 1: EmployeeDailySchedule ─────────────────────────────────────
    if _is_flexible_employee(employee):
        return _flexible_shift(employee, date)

    daily = get_employee_schedule_for_date(employee, date)
    if daily is not None:
        if daily.is_rest_day:
            return {
                'scheduled': False,
                'is_rest_day': True,
                'start_time': None,
                'end_time': None,
                'is_overnight': False,
                'break_minutes': 0,
                'half_day_cutoff_time': None,
                'grace_minutes': 0,
                'overtime_after_minutes': 0,
                'allow_early_clock_in_minutes': 30,
                'source': 'daily_schedule',
                'daily_schedule': daily,
                'shift_template': None,
                'reason': 'Rest day — no attendance expected.',
            }

        template = daily.shift_template
        # Custom times override template times
        start = daily.custom_start_time or (template.start_time if template else None)
        end = daily.custom_end_time or (template.end_time if template else None)

        if start is None or end is None:
            return {
                **_UNSCHEDULED,
                'source': 'daily_schedule',
                'daily_schedule': daily,
                'reason': 'Daily schedule entry has no times configured — contact HR.',
            }

        break_min = (
            daily.break_minutes
            if daily.break_minutes is not None
            else (template.break_minutes if template else 0)
        )
        grace_min = (
            daily.grace_minutes
            if daily.grace_minutes is not None
            else (template.grace_minutes if template else 0)
        )
        ot_after_min = template.overtime_after_minutes if template else 0
        early_min = template.allow_early_clock_in_minutes if template else 30
        # Overnight: explicit flag on template, or implied by end <= start
        is_overnight = (template.is_overnight if template else False) or (end <= start)

        return {
            'scheduled': True,
            'is_rest_day': False,
            'start_time': start,
            'end_time': end,
            'is_overnight': is_overnight,
            'break_minutes': break_min,
            'half_day_cutoff_time': None,
            'grace_minutes': grace_min,
            'overtime_after_minutes': ot_after_min,
            'allow_early_clock_in_minutes': early_min,
            'source': 'daily_schedule',
            'daily_schedule': daily,
            'shift_template': template,
            'reason': '',
        }

    # ── Priority 2: Employee.work_schedule (WorkSchedule) ─────────────────────
    work_schedule = getattr(employee, 'work_schedule', None)
    if work_schedule and work_schedule.is_active:
        day_field = _DAY_FIELDS[date.weekday()]
        is_workday = getattr(work_schedule, day_field, False)

        if not is_workday:
            return {
                'scheduled': False,
                'is_rest_day': True,
                'start_time': None,
                'end_time': None,
                'is_overnight': False,
                'break_minutes': work_schedule.break_minutes or 0,
                'half_day_cutoff_time': work_schedule.half_day_cutoff_time,
                'grace_minutes': work_schedule.grace_minutes or 0,
                'overtime_after_minutes': 0,
                'allow_early_clock_in_minutes': 30,
                'source': 'work_schedule',
                'daily_schedule': None,
                'shift_template': None,
                'reason': 'Rest day per default work schedule.',
            }

        # Compute overtime_after_minutes from absolute time field on WorkSchedule
        end_time = work_schedule.end_time
        ot_after_time = work_schedule.overtime_after or end_time
        ot_end_min = ot_after_time.hour * 60 + ot_after_time.minute
        end_min = end_time.hour * 60 + end_time.minute
        ot_after_minutes = max(0, ot_end_min - end_min)

        return {
            'scheduled': True,
            'is_rest_day': False,
            'start_time': work_schedule.start_time,
            'end_time': end_time,
            'is_overnight': False,
            'break_minutes': work_schedule.break_minutes or 0,
            'half_day_cutoff_time': work_schedule.half_day_cutoff_time,
            'grace_minutes': work_schedule.grace_minutes or 0,
            'overtime_after_minutes': ot_after_minutes,
            'allow_early_clock_in_minutes': 30,
            'source': 'work_schedule',
            'daily_schedule': None,
            'shift_template': None,
            'reason': '',
        }

    # ── Priority 3: No schedule ────────────────────────────────────────────────
    return dict(_UNSCHEDULED)


def employee_has_schedule_today(employee, date=None):
    """Return True if the employee is expected to work on the given date."""
    if date is None:
        date = datetime.date.today()
    return resolve_expected_shift(employee, date)['scheduled']


def get_allowed_clock_window(employee, date=None):
    """
    Return (earliest_allowed_clock_in, scheduled_end) as datetime objects,
    or (None, None) if the employee has no schedule on that date.

    earliest_clock_in = scheduled_start - allow_early_clock_in_minutes
    """
    if date is None:
        date = datetime.date.today()
    shift = resolve_expected_shift(employee, date)
    if not shift['scheduled'] or not shift['start_time']:
        return None, None

    start_dt = datetime.datetime.combine(date, shift['start_time'])
    earliest = start_dt - datetime.timedelta(minutes=shift['allow_early_clock_in_minutes'])

    end_date = date + datetime.timedelta(days=1) if shift['is_overnight'] else date
    end_dt = datetime.datetime.combine(end_date, shift['end_time'])

    return earliest, end_dt
