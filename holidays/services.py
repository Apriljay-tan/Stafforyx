"""Resolve the effective holiday (and pay parameters) for an employee on a date.

Batch builders let payroll resolve many employees/dates with few queries.
"""
from collections import defaultdict

from .constants import TYPE_PRIORITY
from .models import Holiday, HolidayException


def build_holiday_index(company, start_date, end_date):
    """{date: [Holiday, ...]} for enabled holidays in [start, end], sorted by priority."""
    index = defaultdict(list)
    qs = Holiday.objects.filter(
        company=company, is_enabled=True,
        date__gte=start_date, date__lte=end_date,
    )
    for h in qs:
        index[h.date].append(h)
    for date in index:
        index[date].sort(key=lambda h: TYPE_PRIORITY.get(h.holiday_type, 99))
    return index


def build_exception_index(company):
    """{holiday_id: {'dept': {dept_id: exc}, 'emp': {emp_id: exc}}}."""
    index = defaultdict(lambda: {"dept": {}, "emp": {}})
    qs = HolidayException.objects.filter(holiday__company=company)
    for exc in qs.select_related("holiday"):
        if exc.employee_id:
            index[exc.holiday_id]["emp"][exc.employee_id] = exc
        elif exc.department_id:
            index[exc.holiday_id]["dept"][exc.department_id] = exc
    return index


def _effective_params(holiday, exc):
    is_paid = holiday.is_paid
    no_work_pct = holiday.no_work_pay_pct
    worked_mult = holiday.worked_multiplier
    if exc is not None:
        if exc.is_paid_override is not None:
            is_paid = exc.is_paid_override
        if exc.no_work_pay_pct_override is not None:
            no_work_pct = exc.no_work_pay_pct_override
        if exc.worked_multiplier_override is not None:
            worked_mult = exc.worked_multiplier_override
    return {
        "holiday": holiday,
        "is_paid": is_paid,
        "no_work_pay_pct": no_work_pct,
        "worked_multiplier": worked_mult,
    }


def resolve_holiday(company, employee, date, holiday_index, exception_index):
    """Return effective holiday pay params for employee+date, or None.

    None means: no holiday, all holidays disabled, or an exception marks the
    highest-priority holiday `not_observed` for this employee/department.
    """
    candidates = holiday_index.get(date)
    if not candidates:
        return None

    holiday = candidates[0]  # highest priority
    exc_for_holiday = exception_index.get(holiday.id)
    exc = None
    if exc_for_holiday:
        exc = exc_for_holiday["emp"].get(employee.id)
        if exc is None and employee.department_id:
            exc = exc_for_holiday["dept"].get(employee.department_id)

    if exc is not None and exc.not_observed:
        return None

    return _effective_params(holiday, exc)
