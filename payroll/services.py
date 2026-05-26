from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db import IntegrityError

from attendance.models import AttendanceRecord
from employees.models import Employee
from .models import PayrollRecord

_DAILY_DIVISOR = Decimal('26')
_HOURS_PER_DAY = Decimal('8')
_OT_MULTIPLIER = Decimal('1.25')


def _count_weekdays(start_date, end_date):
    count = 0
    current = start_date
    while current <= end_date:
        if current.weekday() < 5:
            count += 1
        current += timedelta(days=1)
    return count


def generate_payroll_for_period(period, department_id=None):
    """
    Create draft PayrollRecords for every active employee in the period's company.
    Prorates basic_pay by weekdays in the period (salary / 26 * weekdays).
    Populates late_deduction, overtime_pay, absence_deduction from AttendanceRecords.
    Existing period+employee records are skipped (unique_together constraint).
    Returns (created_count, skipped_count).
    """
    employees = (
        Employee.objects
        .filter(company=period.company, status='active')
        .select_related('department')
    )
    if department_id:
        employees = employees.filter(department_id=department_id)

    emp_list = list(employees)
    if not emp_list:
        return 0, 0

    att_records = AttendanceRecord.objects.filter(
        employee__in=emp_list,
        date__gte=period.start_date,
        date__lte=period.end_date,
    )
    att_map = defaultdict(list)
    for rec in att_records:
        att_map[rec.employee_id].append(rec)

    period_weekdays = _count_weekdays(period.start_date, period.end_date)

    created, skipped = 0, 0
    for emp in emp_list:
        salary = Decimal(str(emp.basic_salary))
        daily_rate = salary / _DAILY_DIVISOR
        hourly_rate = daily_rate / _HOURS_PER_DAY

        records = att_map.get(emp.pk, [])
        late_min = sum(r.late_minutes or 0 for r in records)
        ot_min = sum(r.overtime_minutes or 0 for r in records)
        absent_days = sum(
            1 for r in records
            if (r.computed_status or r.status) == 'absent'
        )

        late_ded = (Decimal(late_min) / 60 * hourly_rate).quantize(Decimal('0.01'))
        ot_pay = (Decimal(ot_min) / 60 * hourly_rate * _OT_MULTIPLIER).quantize(Decimal('0.01'))
        absence_ded = (Decimal(absent_days) * daily_rate).quantize(Decimal('0.01'))

        basic_pay = (daily_rate * period_weekdays).quantize(Decimal('0.01'))
        gross_pay = (basic_pay + ot_pay).quantize(Decimal('0.01'))
        net_pay = (gross_pay - late_ded - absence_ded).quantize(Decimal('0.01'))

        try:
            PayrollRecord.objects.create(
                company=period.company,
                payroll_period=period,
                employee=emp,
                basic_pay=basic_pay,
                overtime_pay=ot_pay,
                gross_pay=gross_pay,
                late_deduction=late_ded,
                absence_deduction=absence_ded,
                net_pay=net_pay,
                status='draft',
            )
            created += 1
        except IntegrityError:
            skipped += 1

    return created, skipped
