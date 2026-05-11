"""
Attendance computation helpers.

compute_attendance(record) — reads the employee's assigned WorkSchedule and
populates the derived fields on an AttendanceRecord, then saves them.
"""

_DAY_FIELDS = [
    'work_monday', 'work_tuesday', 'work_wednesday', 'work_thursday',
    'work_friday', 'work_saturday', 'work_sunday',
]


def _to_min(t):
    """Convert a time object to minutes since midnight."""
    return t.hour * 60 + t.minute


def compute_attendance(record):
    """
    Compute late_minutes, undertime_minutes, overtime_minutes,
    total_work_minutes, and computed_status for a single AttendanceRecord,
    then save those fields.

    Rules:
    - No schedule → present/incomplete/no_schedule based on time fields.
    - Non-workday → rest_day (no late/undertime/overtime).
    - Missing time_in on workday → absent.
    - Missing time_out on workday → incomplete.
    - Overtime negates undertime (employee left late, so no undertime).
    """
    schedule = getattr(record.employee, 'work_schedule', None)

    late_min = 0
    undertime_min = 0
    overtime_min = 0
    total_work_min = 0
    computed = ''

    if schedule is None:
        if record.time_in and not record.time_out:
            computed = 'incomplete'
        elif record.time_in and record.time_out:
            total_work_min = max(
                0,
                _to_min(record.time_out) - _to_min(record.time_in) - (record.break_minutes or 0)
            )
            computed = 'present'
        else:
            computed = 'no_schedule'
    else:
        weekday = record.date.weekday()  # 0 = Monday
        is_workday = getattr(schedule, _DAY_FIELDS[weekday], False)

        if not is_workday:
            if record.time_in and record.time_out:
                total_work_min = max(
                    0,
                    _to_min(record.time_out) - _to_min(record.time_in) - (record.break_minutes or 0)
                )
            computed = 'rest_day'

        elif not record.time_in:
            computed = 'absent'

        else:
            # Scheduled workday with a time_in
            sched_start_min = _to_min(schedule.start_time)
            grace = schedule.grace_minutes or 0
            time_in_min = _to_min(record.time_in)
            late_min = max(0, time_in_min - (sched_start_min + grace))

            if not record.time_out:
                computed = 'incomplete'
            else:
                time_out_min = _to_min(record.time_out)
                break_min = record.break_minutes or 0
                total_work_min = max(0, time_out_min - time_in_min - break_min)

                required_min = int(float(schedule.required_hours) * 60)
                undertime_min = max(0, required_min - total_work_min)

                ot_after = schedule.overtime_after or schedule.end_time
                ot_start_min = _to_min(ot_after)
                overtime_min = max(0, time_out_min - ot_start_min)

                # Overtime cancels undertime — employee stayed past end time
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
    record.computed_status = computed
    record.save(update_fields=[
        'late_minutes', 'undertime_minutes', 'overtime_minutes',
        'total_work_minutes', 'computed_status',
    ])
