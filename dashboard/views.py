from decimal import Decimal

from django.db.models import DecimalField, Sum, Value
from django.db.models.functions import Coalesce
from django.shortcuts import render
from django.utils import timezone

from announcements.models import Announcement
from attendance.models import AttendanceRecord
from employees.models import Employee
from leaves.models import LeaveRequest
from payroll.models import PayrollRecord


def dashboard_home(request):
    today = timezone.localdate()

    active_employee_count = Employee.objects.filter(status='active').count()
    present_today_count = AttendanceRecord.objects.filter(
        date=today,
        status='present',
    ).count()
    pending_leave_count = LeaveRequest.objects.filter(status='pending').count()
    payroll_month_total = PayrollRecord.objects.filter(
        payroll_period__start_date__year=today.year,
        payroll_period__start_date__month=today.month,
    ).aggregate(
        total=Coalesce(
            Sum('net_pay'),
            Value(Decimal('0.00')),
            output_field=DecimalField(max_digits=12, decimal_places=2),
        )
    )['total']

    context = {
        'today': today,
        'active_employee_count': active_employee_count,
        'present_today_count': present_today_count,
        'pending_leave_count': pending_leave_count,
        'payroll_month_total': payroll_month_total,
        'recent_employees': Employee.objects.select_related(
            'company', 'department', 'position'
        ).order_by('-created_at')[:5],
        'recent_attendance_records': AttendanceRecord.objects.select_related(
            'employee', 'employee__department'
        )[:5],
        'recent_leave_requests': LeaveRequest.objects.select_related(
            'employee', 'leave_type'
        )[:5],
        'recent_announcements': Announcement.objects.select_related(
            'company', 'target_department'
        )[:5],
    }
    return render(request, "dashboard/index.html", context)
