"""
Payroll Engine V2
=================

Formula (payable-days approach — no double-deduction on absences):
    daily_rate   = basic_salary / 26
    hourly_rate  = daily_rate / 8

    scheduled_days   = dates in period where employee is expected to work
                       (resolved via Phase-2 EmployeeDailySchedule → WorkSchedule priority)
    paid_leave_days  = approved paid-leave days that fall on scheduled working days
    unpaid_leave_days= approved unpaid-leave days that fall on scheduled working days
    present_days     = scheduled days where employee clocked in (not covered by leave)
    absent_days      = scheduled_days - present_days - paid_leave_days - unpaid_leave_days

    payable_days = present_days + paid_leave_days
    basic_pay    = daily_rate × payable_days
                   (absent days are already excluded — absence_deduction is stored for
                    display/reporting only and is NOT subtracted again in net_pay)

    overtime_pay        = (overtime_minutes / 60) × hourly_rate × 1.25
    late_deduction      = (late_minutes / 60) × hourly_rate
    undertime_deduction = (undertime_minutes / 60) × hourly_rate

    gross_pay       = basic_pay + overtime_pay + allowances [+ earning adjustments]
    total_deductions= sss + philhealth + pagibig + tax
                      + late_deduction + undertime_deduction
                      + other_deductions [+ deduction adjustments]
    net_pay         = gross_pay − total_deductions

Regenerate behaviour:
    - Draft records   → recalculated and updated.
    - Approved / Paid → skipped (unless allow_overwrite=True is passed).
    - Missing records → created.
    Returns (created, updated_draft, skipped_locked).
"""

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from attendance.models import AttendanceRecord, EmployeeDailySchedule
from employees.models import Employee
from holidays.services import build_exception_index, build_holiday_index, resolve_holiday
from leaves.models import LeaveRequest

from .models import PayrollRecord
from overtime.services import build_overtime_approval_index, payable_overtime_minutes

_DAILY_DIVISOR = Decimal('26')
_HOURS_PER_DAY = Decimal('8')
_OT_MULTIPLIER = Decimal('1.25')
_Q2 = Decimal('0.01')
_Q4 = Decimal('0.0001')

_WEEK_FIELDS = [
    'work_monday', 'work_tuesday', 'work_wednesday',
    'work_thursday', 'work_friday', 'work_saturday', 'work_sunday',
]


# ── Schedule helper (batch) ────────────────────────────────────────────────────

def _build_scheduled_sets(employees, start_date, end_date):
    """
    Return {employee.pk: set_of_scheduled_dates} for [start_date, end_date].
    Uses two bulk queries (daily schedules + work schedules already on employees).
    """
    dates = []
    cur = start_date
    while cur <= end_date:
        dates.append(cur)
        cur += timedelta(days=1)

    # Bulk-load daily schedules for all employees in the period
    daily_qs = EmployeeDailySchedule.objects.filter(
        employee__in=employees,
        schedule_date__gte=start_date,
        schedule_date__lte=end_date,
    ).select_related('shift_template')

    by_emp_date = defaultdict(dict)
    for ds in daily_qs:
        by_emp_date[ds.employee_id][ds.schedule_date] = ds

    result = {}
    for emp in employees:
        ws = getattr(emp, 'work_schedule', None)
        emp_daily = by_emp_date.get(emp.pk, {})
        scheduled = set()

        for date in dates:
            ds = emp_daily.get(date)
            if ds is not None:
                # Daily schedule exists: rest day → not scheduled; else check times
                if not ds.is_rest_day:
                    has_times = bool(
                        ds.shift_template_id or
                        (ds.custom_start_time and ds.custom_end_time)
                    )
                    if has_times:
                        scheduled.add(date)
            elif ws and ws.is_active:
                if getattr(ws, _WEEK_FIELDS[date.weekday()], False):
                    scheduled.add(date)

        result[emp.pk] = scheduled

    return result


# ── Leave helper (batch) ───────────────────────────────────────────────────────

def _build_leave_maps(employees, start_date, end_date, scheduled_sets):
    """
    Return ({emp_pk: set_of_paid_leave_dates}, {emp_pk: set_of_unpaid_leave_dates}).
    Only counts leave dates that fall on that employee's scheduled working days.
    """
    leaves = LeaveRequest.objects.filter(
        employee__in=employees,
        status='approved',
        start_date__lte=end_date,
        end_date__gte=start_date,
    ).select_related('leave_type')

    paid_map = defaultdict(set)
    unpaid_map = defaultdict(set)

    for leave in leaves:
        scheduled = scheduled_sets.get(leave.employee_id, set())
        cur = max(leave.start_date, start_date)
        end = min(leave.end_date, end_date)
        while cur <= end:
            if cur in scheduled:
                if leave.leave_type.is_paid:
                    paid_map[leave.employee_id].add(cur)
                else:
                    unpaid_map[leave.employee_id].add(cur)
            cur += timedelta(days=1)

    return paid_map, unpaid_map


# ── Attendance helper (batch) ──────────────────────────────────────────────────

def _build_attendance_map(employees, start_date, end_date):
    """Return {emp_pk: {date: AttendanceRecord}}."""
    records = AttendanceRecord.objects.filter(
        employee__in=employees,
        date__gte=start_date,
        date__lte=end_date,
    )
    result = defaultdict(dict)
    for r in records:
        result[r.employee_id][r.date] = r
    return result


# ── Per-employee calculation ───────────────────────────────────────────────────

def _calc_employee_payroll(emp, scheduled_dates, paid_leave_dates, unpaid_leave_dates,
                           att_by_date, holiday_resolver, approval_index):
    """
    Compute all payroll components for one employee.

    `holiday_resolver(emp, date)` returns effective holiday params dict or None.
    Holiday dates are handled in a dedicated pass and excluded from the normal
    present/absent classification so base pay is not double-counted.
    Returns a flat dict of field values ready to save to PayrollRecord.
    """
    salary = Decimal(str(emp.basic_salary or 0))
    daily_rate = (salary / _DAILY_DIVISOR).quantize(_Q4, rounding=ROUND_HALF_UP)
    hourly_rate = (daily_rate / _HOURS_PER_DAY).quantize(_Q4, rounding=ROUND_HALF_UP)
    is_monthly = getattr(emp, 'pay_basis', 'daily') == 'monthly'

    present_dates = set()
    absent_dates = set()
    late_min = 0
    undertime_min = 0
    overtime_min = 0

    holiday_pay = Decimal('0')
    holiday_days = 0
    holiday_worked_days = 0

    # Dates to evaluate for holidays: scheduled days plus any attended day.
    holiday_candidate_dates = set(scheduled_dates) | set(att_by_date.keys())

    for date in scheduled_dates:
        # Leave-covered → do not count toward present/absent
        if date in paid_leave_dates or date in unpaid_leave_dates:
            continue

        holiday = holiday_resolver(emp, date)
        if holiday is not None:
            # Handled in the holiday pass below; skip normal classification.
            continue

        att = att_by_date.get(date)
        if att and att.time_in is not None:
            present_dates.add(date)
            late_min += att.late_minutes or 0
            undertime_min += att.undertime_minutes or 0
            overtime_min += payable_overtime_minutes(
                emp, date, att.overtime_minutes or 0, approval_index
            )
        else:
            absent_dates.add(date)

    # ── Holiday pass ──────────────────────────────────────────────────────────
    for date in holiday_candidate_dates:
        # Leave-covered holidays are paid via leave, not here.
        if date in paid_leave_dates or date in unpaid_leave_dates:
            continue
        holiday = holiday_resolver(emp, date)
        if holiday is None:
            continue

        att = att_by_date.get(date)
        worked = bool(att and att.time_in is not None)
        is_scheduled = date in scheduled_dates

        if worked:
            holiday_days += 1
            holiday_worked_days += 1
            holiday_pay += daily_rate * Decimal(str(holiday['worked_multiplier']))
            # Worked-day late/UT/OT still apply.
            late_min += att.late_minutes or 0
            undertime_min += att.undertime_minutes or 0
            overtime_min += payable_overtime_minutes(
                emp, date, att.overtime_minutes or 0, approval_index
            )
        elif is_scheduled:
            # No-work holiday on a scheduled day.
            effective_paid = is_monthly or holiday['is_paid']
            if effective_paid:
                holiday_days += 1
                pct = Decimal(str(holiday['no_work_pay_pct']))
                holiday_pay += daily_rate * pct / Decimal('100')
        # else: rest-day, not worked → no pay.

    holiday_pay = holiday_pay.quantize(_Q2, rounding=ROUND_HALF_UP)

    scheduled_days = len(scheduled_dates)
    present_days = len(present_dates)
    paid_leave_days = Decimal(len(paid_leave_dates))
    unpaid_leave_days = Decimal(len(unpaid_leave_dates))
    absent_days = Decimal(len(absent_dates))
    payable_days = Decimal(present_days) + paid_leave_days

    basic_pay = (daily_rate * payable_days).quantize(_Q2, rounding=ROUND_HALF_UP)
    absence_ded = (daily_rate * absent_days).quantize(_Q2, rounding=ROUND_HALF_UP)

    late_ded = (
        Decimal(late_min) / Decimal(60) * hourly_rate
    ).quantize(_Q2, rounding=ROUND_HALF_UP)
    undertime_ded = (
        Decimal(undertime_min) / Decimal(60) * hourly_rate
    ).quantize(_Q2, rounding=ROUND_HALF_UP)
    ot_pay = (
        Decimal(overtime_min) / Decimal(60) * hourly_rate * _OT_MULTIPLIER
    ).quantize(_Q2, rounding=ROUND_HALF_UP)

    # Copy fixed contributions from employee settings at generation time
    sss_ded = Decimal(str(emp.sss_contribution_amount or 0)).quantize(_Q2)
    philhealth_ded = Decimal(str(emp.philhealth_contribution_amount or 0)).quantize(_Q2)
    pagibig_ded = Decimal(str(emp.pagibig_contribution_amount or 0)).quantize(_Q2)
    tax_ded = Decimal(str(emp.tax_deduction_amount or 0)).quantize(_Q2)

    gross_pay = (basic_pay + ot_pay + holiday_pay).quantize(_Q2)
    total_ded = sss_ded + philhealth_ded + pagibig_ded + tax_ded + late_ded + undertime_ded
    net_pay = (gross_pay - total_ded).quantize(_Q2)

    return dict(
        scheduled_days=scheduled_days,
        present_days=present_days,
        paid_leave_days=paid_leave_days,
        unpaid_leave_days=unpaid_leave_days,
        absent_days=absent_days,
        payable_days=payable_days,
        late_minutes=late_min,
        undertime_minutes=undertime_min,
        overtime_minutes=overtime_min,
        daily_rate=daily_rate,
        hourly_rate=hourly_rate,
        basic_pay=basic_pay,
        overtime_pay=ot_pay,
        holiday_pay=holiday_pay,
        holiday_days=holiday_days,
        holiday_worked_days=holiday_worked_days,
        gross_pay=gross_pay,
        late_deduction=late_ded,
        undertime_deduction=undertime_ded,
        absence_deduction=absence_ded,
        sss_deduction=sss_ded,
        philhealth_deduction=philhealth_ded,
        pagibig_deduction=pagibig_ded,
        tax_deduction=tax_ded,
        net_pay=net_pay,
    )


# ── Public API ─────────────────────────────────────────────────────────────────

def generate_payroll_for_period(period, department_id=None, allow_update_draft=True):
    """
    Create or update PayrollRecords for every active employee in the period's company.

    - Missing records          → created (counted in `created`).
    - Draft records            → recalculated if allow_update_draft=True (counted in `updated`).
    - Approved / Paid records  → always skipped (counted in `skipped`).

    Returns (created, updated, skipped).
    """
    employees = (
        Employee.objects
        .filter(company=period.company, status='active')
        .select_related('department', 'work_schedule')
    )
    if department_id:
        employees = employees.filter(department_id=department_id)

    emp_list = list(employees)
    if not emp_list:
        return 0, 0, 0

    start_date = period.start_date
    end_date = period.end_date

    # Batch-resolve schedules, leaves, and attendance
    scheduled_sets = _build_scheduled_sets(emp_list, start_date, end_date)
    paid_map, unpaid_map = _build_leave_maps(emp_list, start_date, end_date, scheduled_sets)
    att_map = _build_attendance_map(emp_list, start_date, end_date)
    approval_index = build_overtime_approval_index(
        period.company, emp_list, start_date, end_date
    )

    # Holiday resolution (bulk-loaded once per period).
    holiday_index = build_holiday_index(period.company, start_date, end_date)
    exception_index = build_exception_index(period.company)

    def _holiday_resolver(emp, date):
        return resolve_holiday(period.company, emp, date, holiday_index, exception_index)

    # Load existing records for efficient lookup
    existing = {
        r.employee_id: r
        for r in PayrollRecord.objects.filter(
            payroll_period=period, employee__in=emp_list
        )
    }

    created = updated = skipped = 0

    for emp in emp_list:
        components = _calc_employee_payroll(
            emp,
            scheduled_sets.get(emp.pk, set()),
            paid_map.get(emp.pk, set()),
            unpaid_map.get(emp.pk, set()),
            att_map.get(emp.pk, {}),
            _holiday_resolver,
            approval_index,
        )

        record = existing.get(emp.pk)

        if record is None:
            PayrollRecord.objects.create(
                company=period.company,
                payroll_period=period,
                employee=emp,
                status='draft',
                **components,
            )
            created += 1

        elif record.status == 'draft' and allow_update_draft:
            for field, value in components.items():
                setattr(record, field, value)
            record.save(update_fields=list(components.keys()))
            record.recalculate()
            updated += 1

        else:
            skipped += 1

    return created, updated, skipped
