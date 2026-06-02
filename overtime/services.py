"""
Overtime payment resolution.

payable_overtime_minutes(...) maps raw *detected* overtime (from the attendance
engine) to the minutes payroll should actually pay, based on the employee's
overtime policy and any approved OvertimeRequest. The attendance engine is never
modified by this module — it only consumes its output.
"""

from decimal import Decimal, ROUND_HALF_UP

_60 = Decimal(60)


def build_overtime_approval_index(company, employees, start_date, end_date):
    """
    Return {(employee_id, date): OvertimeRequest} for approved/auto_approved
    requests in [start_date, end_date]. One query, used by payroll.
    """
    from .models import OvertimeRequest

    qs = OvertimeRequest.objects.filter(
        company=company,
        employee__in=employees,
        date__gte=start_date,
        date__lte=end_date,
        status__in=['approved', 'auto_approved'],
    )
    return {(o.employee_id, o.date): o for o in qs}


def _approved_minutes(request):
    """Approved hours → minutes; approved_hours falls back to requested_hours."""
    hours = request.approved_hours
    if hours is None:
        hours = request.requested_hours
    return int((Decimal(str(hours or 0)) * _60).to_integral_value(rounding=ROUND_HALF_UP))


def payable_overtime_minutes(employee, date, detected_min, approval_index):
    """
    Resolve payable overtime minutes for one employee/date.

    - automatic          → detected.
    - request_required   → 0, or min(detected, approved) if an approved request exists.
    - management_review  → 0, or min(detected, approved) once approved.
    - not_allowed        → 0, unless an approved (HR override) request exists → capped.
    """
    detected_min = detected_min or 0
    policy = getattr(employee, 'overtime_policy', 'not_allowed')

    if policy == 'automatic':
        return detected_min

    request = approval_index.get((employee.id, date))
    if request is None:
        return 0
    return min(detected_min, _approved_minutes(request))
