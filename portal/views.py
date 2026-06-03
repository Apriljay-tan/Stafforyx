import datetime
import mimetypes

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render

from accounts.company_access import filter_queryset_by_user_companies, user_can_access_company
from announcements.models import Announcement
from attendance.models import AttendanceRecord
from attendance.schedule_services import resolve_expected_shift
from documents.models import EmployeeDocument
from leaves.models import LeaveRequest, LeaveType
from overtime.models import OvertimeRequest
from payroll.models import PayrollRecord

from .forms import PortalIncidentReportForm, PortalLeaveRequestForm, PortalOvertimeRequestForm
from .models import IncidentReport


# ── Employee resolver ─────────────────────────────────────────────────────────

def _get_portal_employee(request):
    """Return the Employee linked to this logged-in user, or None."""
    # 1. Direct OneToOne: Employee.user
    try:
        emp = request.user.employee_profile
        if emp is not None:
            return emp
    except Exception:
        pass
    # 2. UserProfile.employee FK
    try:
        profile = request.user.stafforyx_profile
        if profile.employee_id:
            return profile.employee
    except Exception:
        pass
    return None


def _require_portal_employee(request):
    """Return (employee, None) or (None, response) for no_employee page."""
    emp = _get_portal_employee(request)
    if emp is None:
        return None, render(request, 'portal/no_employee.html')
    return emp, None


def _portal_announcements_queryset(employee):
    queryset = Announcement.objects.filter(
        company=employee.company,
        is_active=True,
    ).select_related('company', 'target_department', 'posted_by')
    if employee.department_id:
        queryset = queryset.filter(
            Q(target_department__isnull=True) | Q(target_department=employee.department)
        )
    else:
        queryset = queryset.filter(target_department__isnull=True)
    return queryset.order_by('-created_at')


# ── Portal: Dashboard ─────────────────────────────────────────────────────────

@login_required
def portal_dashboard(request):
    employee, fallback = _require_portal_employee(request)
    if fallback:
        return fallback

    recent_payslips = (
        PayrollRecord.objects
        .filter(employee=employee)
        .select_related('payroll_period')
        .order_by('-payroll_period__start_date')[:3]
    )
    recent_leaves = (
        LeaveRequest.objects
        .filter(employee=employee)
        .select_related('leave_type')
        .order_by('-created_at')[:3]
    )
    recent_attendance = (
        AttendanceRecord.objects
        .filter(employee=employee)
        .order_by('-date')[:5]
    )
    open_incidents = IncidentReport.objects.filter(
        employee=employee, status__in=['submitted', 'under_review']
    ).count()
    recent_announcements = _portal_announcements_queryset(employee)[:5]

    return render(request, 'portal/dashboard.html', {
        'employee': employee,
        'recent_payslips': recent_payslips,
        'recent_leaves': recent_leaves,
        'recent_attendance': recent_attendance,
        'open_incidents': open_incidents,
        'recent_announcements': recent_announcements,
    })


# ── Portal: Payslips ──────────────────────────────────────────────────────────

@login_required
def portal_payslip_list(request):
    employee, fallback = _require_portal_employee(request)
    if fallback:
        return fallback

    payslips = (
        PayrollRecord.objects
        .filter(employee=employee)
        .select_related('payroll_period', 'company')
        .order_by('-payroll_period__start_date')
    )
    return render(request, 'portal/payslip_list.html', {
        'employee': employee,
        'payslips': payslips,
    })


@login_required
def portal_payslip_detail(request, pk):
    employee, fallback = _require_portal_employee(request)
    if fallback:
        return fallback

    # employee=employee in the filter enforces ownership
    record = get_object_or_404(
        PayrollRecord.objects.select_related(
            'company', 'payroll_period', 'employee',
            'employee__department', 'employee__position',
        ).prefetch_related('adjustments'),
        pk=pk,
        employee=employee,
    )

    from decimal import Decimal
    hourly_rate = record.hourly_rate or Decimal('0')
    q2 = Decimal('0.01')

    earning_adjs = record.adjustments.filter(adjustment_type='earning')
    deduction_adjs = record.adjustments.filter(adjustment_type='deduction')

    return render(request, 'portal/payslip_detail.html', {
        'employee': employee,
        'record': record,
        'company': record.company,
        'earning_adjs': earning_adjs,
        'deduction_adjs': deduction_adjs,
        'regular_ot_rate': (hourly_rate * Decimal('1.25')).quantize(q2),
        'rest_day_ot_rate': (hourly_rate * Decimal('1.30')).quantize(q2),
        'holiday_ot_rate': (hourly_rate * Decimal('2.60')).quantize(q2),
    })


# ── Portal: Documents ─────────────────────────────────────────────────────────

@login_required
def portal_documents(request):
    employee, fallback = _require_portal_employee(request)
    if fallback:
        return fallback

    documents = (
        EmployeeDocument.objects
        .filter(employee=employee)
        .order_by('-created_at')
    )
    return render(request, 'portal/documents.html', {
        'employee': employee,
        'documents': documents,
    })


@login_required
def portal_document_download(request, pk):
    employee, fallback = _require_portal_employee(request)
    if fallback:
        raise PermissionDenied

    doc = get_object_or_404(EmployeeDocument, pk=pk, employee=employee)
    mime_type, _ = mimetypes.guess_type(doc.file.name)
    response = FileResponse(
        doc.file.open('rb'),
        content_type=mime_type or 'application/octet-stream',
    )
    filename = doc.file.name.split('/')[-1].split('\\')[-1]
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


# ── Portal: Leaves ────────────────────────────────────────────────────────────

@login_required
def portal_leave_list(request):
    employee, fallback = _require_portal_employee(request)
    if fallback:
        return fallback

    leaves = (
        LeaveRequest.objects
        .filter(employee=employee)
        .select_related('leave_type')
        .order_by('-created_at')
    )
    return render(request, 'portal/leave_list.html', {
        'employee': employee,
        'leaves': leaves,
    })


@login_required
def portal_leave_new(request):
    employee, fallback = _require_portal_employee(request)
    if fallback:
        return fallback

    if request.method == 'POST':
        form = PortalLeaveRequestForm(request.POST, employee=employee)
        if form.is_valid():
            leave = form.save(commit=False)
            leave.employee = employee
            leave.company = employee.company
            leave.status = 'pending'
            leave.save()
            messages.success(request, 'Leave request submitted. Waiting for approval.')
            return redirect('portal:leave_list')
    else:
        form = PortalLeaveRequestForm(employee=employee)

    return render(request, 'portal/leave_new.html', {
        'employee': employee,
        'form': form,
    })


# ── Portal: Incidents ─────────────────────────────────────────────────────────

@login_required
def portal_incident_list(request):
    employee, fallback = _require_portal_employee(request)
    if fallback:
        return fallback

    incidents = (
        IncidentReport.objects
        .filter(employee=employee)
        .order_by('-created_at')
    )
    return render(request, 'portal/incident_list.html', {
        'employee': employee,
        'incidents': incidents,
    })


@login_required
def portal_incident_new(request):
    employee, fallback = _require_portal_employee(request)
    if fallback:
        return fallback

    if request.method == 'POST':
        form = PortalIncidentReportForm(request.POST)
        if form.is_valid():
            incident = form.save(commit=False)
            incident.employee = employee
            incident.company = employee.company
            incident.save()
            messages.success(request, 'Incident report submitted.')
            return redirect('portal:incident_list')
    else:
        form = PortalIncidentReportForm()

    return render(request, 'portal/incident_new.html', {
        'employee': employee,
        'form': form,
    })


# ── Portal: Attendance ────────────────────────────────────────────────────────

@login_required
def portal_attendance(request):
    employee, fallback = _require_portal_employee(request)
    if fallback:
        return fallback

    records = (
        AttendanceRecord.objects
        .filter(employee=employee)
        .order_by('-date')[:60]
    )
    return render(request, 'portal/attendance.html', {
        'employee': employee,
        'records': records,
    })


@login_required
def portal_time_clock(request):
    """Redirect to the existing IP-validated attendance portal."""
    return redirect('attendance:attendance_portal')


# ── Portal: Overtime ──────────────────────────────────────────────────────────

@login_required
def portal_overtime_list(request):
    employee, fallback = _require_portal_employee(request)
    if fallback:
        return fallback

    today = datetime.date.today()
    shift = resolve_expected_shift(employee, today)
    requests = (
        OvertimeRequest.objects
        .filter(employee=employee)
        .order_by('-date')
    )
    can_request = employee.overtime_policy != 'not_allowed'

    return render(request, 'portal/overtime_list.html', {
        'employee': employee,
        'requests': requests,
        'today': today,
        'shift': shift,
        'can_request': can_request,
        'policy_display': employee.get_overtime_policy_display(),
    })


@login_required
def portal_overtime_new(request):
    employee, fallback = _require_portal_employee(request)
    if fallback:
        return fallback

    if employee.overtime_policy == 'not_allowed':
        messages.error(request, 'Overtime requests are not allowed for your account.')
        return redirect('portal:overtime_list')

    if request.method == 'POST':
        form = PortalOvertimeRequestForm(request.POST)
        if form.is_valid():
            date = form.cleaned_data['date']
            if OvertimeRequest.objects.filter(employee=employee, date=date).exists():
                messages.warning(
                    request,
                    'You already have an overtime request for that date.',
                )
                return redirect('portal:overtime_list')
            ot = form.save(commit=False)
            ot.employee = employee
            ot.company = employee.company
            ot.status = 'pending'
            ot.source = 'employee'
            ot.save()
            messages.success(request, 'Overtime request submitted. Waiting for approval.')
            return redirect('portal:overtime_list')
    else:
        form = PortalOvertimeRequestForm()

    return render(request, 'portal/overtime_new.html', {
        'employee': employee,
        'form': form,
    })


# —— Portal: Announcements ———————————————————————————————————————————————————————————

@login_required
def portal_announcements(request):
    employee, fallback = _require_portal_employee(request)
    if fallback:
        return fallback

    announcements = _portal_announcements_queryset(employee)
    return render(request, 'portal/announcements.html', {
        'employee': employee,
        'announcements': announcements,
    })


@login_required
def portal_announcement_detail(request, pk):
    employee, fallback = _require_portal_employee(request)
    if fallback:
        return fallback

    announcement = get_object_or_404(
        _portal_announcements_queryset(employee),
        pk=pk,
    )
    return render(request, 'portal/announcement_detail.html', {
        'employee': employee,
        'announcement': announcement,
    })


@login_required
def portal_notifications_seen(request):
    """Mark the notification bell as read (called when the popup opens)."""
    from django.http import JsonResponse
    from django.utils import timezone
    from announcements.models import AnnouncementSeen

    employee = _get_portal_employee(request)
    if employee is not None and request.method == 'POST':
        AnnouncementSeen.objects.update_or_create(
            employee=employee, defaults={'last_seen_at': timezone.now()},
        )
        return JsonResponse({'ok': True})
    return JsonResponse({'ok': False}, status=400)


# ── HR: Manage Incidents ──────────────────────────────────────────────────────

@login_required
def manage_incidents(request):
    """HR/admin view — incident reports scoped to accessible companies."""
    profile = getattr(request.user, 'stafforyx_profile', None)
    is_hr = request.user.is_superuser or (profile and profile.can_manage_employees)
    if not is_hr:
        raise PermissionDenied

    incidents = filter_queryset_by_user_companies(
        IncidentReport.objects.select_related('employee', 'company').order_by('-created_at'),
        request.user,
    )
    status_filter = request.GET.get('status', '')
    if status_filter:
        incidents = incidents.filter(status=status_filter)

    return render(request, 'portal/manage_incidents.html', {
        'incidents': incidents,
        'status_filter': status_filter,
        'status_choices': IncidentReport.STATUS_CHOICES,
    })


@login_required
def manage_incident_detail(request, pk):
    """HR can view and update an incident's status and notes."""
    profile = getattr(request.user, 'stafforyx_profile', None)
    is_hr = request.user.is_superuser or (profile and profile.can_manage_employees)
    if not is_hr:
        raise PermissionDenied

    incident = get_object_or_404(
        IncidentReport.objects.select_related('employee', 'company'), pk=pk
    )
    if not user_can_access_company(request.user, incident.company):
        raise PermissionDenied

    if request.method == 'POST':
        new_status = request.POST.get('status', incident.status)
        admin_notes = request.POST.get('admin_notes', incident.admin_notes)
        if new_status in dict(IncidentReport.STATUS_CHOICES):
            incident.status = new_status
            incident.admin_notes = admin_notes
            incident.save(update_fields=['status', 'admin_notes', 'updated_at'])
            messages.success(request, 'Incident report updated.')
        return redirect('portal:manage_incidents')

    return render(request, 'portal/manage_incident_detail.html', {
        'incident': incident,
        'status_choices': IncidentReport.STATUS_CHOICES,
    })
