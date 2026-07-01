import datetime
import mimetypes

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from accounts.avatars import avatar_for_employee
from accounts.company_access import (
    filter_queryset_by_user_companies,
    get_accessible_companies,
    user_can_access_company,
)
from accounts.profile_images import validate_profile_image
from announcements.models import Announcement
from attendance.models import AttendanceRecord
from attendance.schedule_services import resolve_expected_shift
from documents.models import EmployeeDocument
from employees.models import Employee
from leaves.models import LeaveRequest, LeaveType
from notifications.models import Notification
from notifications.services import (
    create_request_notifications,
    delete_notifications_for_objects,
    mark_notifications_read,
    request_notification_target_url,
)
from overtime.models import OvertimeRequest
from payroll.models import PayrollRecord

from cash_advance.models import CashAdvanceRequest

from .forms import (
    PortalCashAdvanceRequestForm,
    PortalIncidentReportForm,
    PortalLeaveRequestForm,
    PortalOvertimeRequestForm,
)
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


def _attach_payroll_display(record):
    totals = record.calculate_totals()
    record.display_gross_pay = totals['gross_pay']
    record.display_total_deductions = totals['total_deductions']
    record.display_net_pay = totals['net_pay']
    record.show_daily_rate = bool(record.basic_pay or record.payable_days)
    record.show_hourly_rate = bool(
        record.overtime_pay or record.overtime_minutes or
        record.late_deduction or record.late_minutes or
        record.undertime_deduction or record.undertime_minutes
    )
    record.show_regular_ot_rate = bool(record.overtime_pay or record.overtime_minutes)
    record.show_rest_day_ot_rate = False
    record.show_holiday_ot_rate = False
    record.show_rate_information = any((
        record.show_daily_rate,
        record.show_hourly_rate,
        record.show_regular_ot_rate,
        record.show_rest_day_ot_rate,
        record.show_holiday_ot_rate,
    ))
    return record


# ── Portal: Dashboard ─────────────────────────────────────────────────────────

@login_required
def portal_dashboard(request):
    employee, fallback = _require_portal_employee(request)
    if fallback:
        return fallback

    recent_payslips = (
        PayrollRecord.objects
        .filter(employee=employee, status__in=PayrollRecord.EMPLOYEE_VISIBLE_STATUSES)
        .select_related('payroll_period')
        .prefetch_related('adjustments')
        .order_by('-payroll_period__start_date')[:3]
    )
    for payslip in recent_payslips:
        _attach_payroll_display(payslip)
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
        .filter(employee=employee, status__in=PayrollRecord.EMPLOYEE_VISIBLE_STATUSES)
        .select_related('payroll_period', 'company')
        .prefetch_related('adjustments')
        .order_by('-payroll_period__start_date')
    )
    for payslip in payslips:
        _attach_payroll_display(payslip)
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
        status__in=PayrollRecord.EMPLOYEE_VISIBLE_STATUSES,
    )

    from decimal import Decimal
    hourly_rate = record.hourly_rate or Decimal('0')
    q2 = Decimal('0.01')

    earning_adjs = record.adjustments.filter(adjustment_type='earning')
    deduction_adjs = record.adjustments.filter(adjustment_type='deduction')
    _attach_payroll_display(record)

    return render(request, 'portal/payslip_detail.html', {
        'employee': employee,
        'record': record,
        'company': record.company,
        'earning_adjs': earning_adjs,
        'deduction_adjs': deduction_adjs,
        'gross_pay': record.display_gross_pay,
        'total_deductions': record.display_total_deductions,
        'net_pay': record.display_net_pay,
        'regular_ot_rate': (
            hourly_rate * Decimal(str(record.overtime_multiplier or '1.25'))
        ).quantize(q2),
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
            create_request_notifications(
                leave,
                Notification.TYPE_LEAVE_REQUEST,
                'New leave request',
                f'{employee.full_name} submitted a leave request.',
                request_notification_target_url(leave),
            )
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
            create_request_notifications(
                incident,
                Notification.TYPE_INCIDENT_REPORT,
                'New incident report',
                f'{employee.full_name} submitted an incident report: {incident.title}',
                request_notification_target_url(incident),
            )
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
    overtime_mode = employee.overtime_mode
    can_request = employee.can_request_overtime

    return render(request, 'portal/overtime_list.html', {
        'employee': employee,
        'requests': requests,
        'today': today,
        'shift': shift,
        'can_request': can_request,
        'overtime_mode': overtime_mode,
        'policy_display': employee.get_overtime_policy_display(),
    })


@login_required
def portal_overtime_new(request):
    employee, fallback = _require_portal_employee(request)
    if fallback:
        return fallback

    if not employee.can_request_overtime:
        if employee.overtime_mode == employee.OVERTIME_AUTOMATIC:
            messages.info(request, 'Overtime is automatically computed from your attendance.')
        else:
            messages.info(request, 'Overtime requests are not enabled for your account.')
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
            create_request_notifications(
                ot,
                Notification.TYPE_OVERTIME_REQUEST,
                'New overtime request',
                f'{employee.full_name} requested {ot.requested_hours} overtime hours.',
                request_notification_target_url(ot),
            )
            messages.success(request, 'Overtime request submitted. Waiting for approval.')
            return redirect('portal:overtime_list')
    else:
        form = PortalOvertimeRequestForm()

    return render(request, 'portal/overtime_new.html', {
        'employee': employee,
        'form': form,
    })


# ── Portal: Cash Advance ──────────────────────────────────────────────────────

@login_required
def portal_ca_list(request):
    employee, fallback = _require_portal_employee(request)
    if fallback:
        return fallback

    requests = (
        CashAdvanceRequest.objects
        .filter(employee=employee)
        .order_by('-created_at')
    )
    return render(request, 'portal/ca_list.html', {
        'employee': employee,
        'requests': requests,
    })


@login_required
def portal_ca_new(request):
    employee, fallback = _require_portal_employee(request)
    if fallback:
        return fallback

    if request.method == 'POST':
        form = PortalCashAdvanceRequestForm(request.POST)
        if form.is_valid():
            ca = form.save(commit=False)
            ca.employee = employee
            ca.company = employee.company
            ca.status = CashAdvanceRequest.STATUS_PENDING
            ca.save()
            create_request_notifications(
                ca,
                Notification.TYPE_CASH_ADVANCE_REQUEST,
                'New cash advance request',
                f'{employee.full_name} requested a cash advance of PHP {ca.amount}.',
                request_notification_target_url(ca),
            )
            messages.success(request, 'Cash advance request submitted. Waiting for approval.')
            return redirect('portal:ca_list')
    else:
        form = PortalCashAdvanceRequestForm()

    return render(request, 'portal/ca_new.html', {
        'employee': employee,
        'form': form,
    })


@login_required
def portal_ca_edit(request, pk):
    employee, fallback = _require_portal_employee(request)
    if fallback:
        return fallback

    # employee=employee enforces ownership — no cross-employee access.
    ca = get_object_or_404(CashAdvanceRequest, pk=pk, employee=employee)

    if not ca.is_editable_by_employee:
        messages.info(request, 'This cash advance request can no longer be edited.')
        return redirect('portal:ca_list')

    if request.method == 'POST':
        form = PortalCashAdvanceRequestForm(request.POST, instance=ca)
        if form.is_valid():
            form.save()
            messages.success(request, 'Cash advance request updated.')
            return redirect('portal:ca_list')
    else:
        form = PortalCashAdvanceRequestForm(instance=ca)

    return render(request, 'portal/ca_new.html', {
        'employee': employee,
        'form': form,
        'editing': True,
        'ca': ca,
    })


@login_required
def portal_ca_cancel(request, pk):
    employee, fallback = _require_portal_employee(request)
    if fallback:
        return fallback

    ca = get_object_or_404(CashAdvanceRequest, pk=pk, employee=employee)
    if request.method == 'POST':
        if ca.is_editable_by_employee:
            ca.status = CashAdvanceRequest.STATUS_CANCELLED
            ca.cancel_reason = 'Cancelled by employee.'
            ca.save(update_fields=['status', 'cancel_reason', 'updated_at'])
            messages.success(request, 'Cash advance request cancelled.')
        else:
            messages.info(request, 'This cash advance request can no longer be cancelled.')
    return redirect('portal:ca_list')


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

INCIDENT_REPORT_ROLES = {'owner', 'company_admin', 'hr_admin', 'attendance_officer'}
INCIDENT_HISTORY_STATUSES = ['resolved', 'rejected']
INCIDENT_TAB_DEFS = [
    ('submitted', 'Submitted', {'status': 'submitted'}),
    ('under_review', 'Under Review', {'status': 'under_review'}),
    ('resolved', 'Resolved', {'status': 'resolved'}),
    ('rejected', 'Rejected', {'status': 'rejected'}),
    ('history', 'History', {'status__in': INCIDENT_HISTORY_STATUSES}),
]
INCIDENT_TAB_FILTERS = {key: filters for key, _label, filters in INCIDENT_TAB_DEFS}


def _user_can_manage_incident_reports(user):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True

    profile = getattr(user, 'stafforyx_profile', None)
    if profile and profile.role == 'super_admin':
        return True

    has_role_access = user.company_accesses.filter(
        is_active=True,
        role__in=INCIDENT_REPORT_ROLES,
    ).exists()
    if has_role_access:
        return True

    return bool(
        profile
        and profile.is_active_stafforyx
        and (profile.can_manage_employees or profile.can_manage_attendance)
        and get_accessible_companies(user).exists()
    )


def _require_incident_report_access(user):
    if not _user_can_manage_incident_reports(user):
        raise PermissionDenied


def _scoped_incident_queryset(user):
    return filter_queryset_by_user_companies(
        IncidentReport.objects.select_related(
            'employee',
            'company',
            'reviewed_by',
        ).order_by('-created_at'),
        user,
    )


def _selected_ids(request):
    return [
        int(value)
        for value in request.POST.getlist('selected_ids')
        if str(value).isdigit()
    ]


def _incident_history_redirect():
    return redirect(f"{reverse('incident_reports:list')}?tab=history")


@login_required
def manage_incidents(request):
    _require_incident_report_access(request.user)

    tab = request.GET.get('tab', 'submitted')
    if tab not in INCIDENT_TAB_FILTERS:
        tab = 'submitted'

    if request.method == 'POST':
        if request.POST.get('action') == 'delete_selected':
            if tab != 'history':
                messages.warning(request, 'Incident reports can only be deleted from History.')
                return redirect(f"{reverse('incident_reports:list')}?tab={tab}")

            selected_ids = _selected_ids(request)
            delete_queryset = _scoped_incident_queryset(request.user).filter(
                pk__in=selected_ids,
                status__in=INCIDENT_HISTORY_STATUSES,
            )
            delete_ids = list(delete_queryset.values_list('pk', flat=True))
            if delete_ids:
                delete_notifications_for_objects(IncidentReport, delete_ids)
                deleted_count, _details = delete_queryset.delete()
                messages.success(request, f'Deleted {deleted_count} incident report(s).')
            else:
                messages.info(request, 'No closed incident reports were selected for deletion.')
            return _incident_history_redirect()

        incident = get_object_or_404(
            _scoped_incident_queryset(request.user),
            pk=request.POST.get('incident_id'),
        )
        if not user_can_access_company(request.user, incident.company):
            raise PermissionDenied
        new_status = request.POST.get('status', incident.status)
        if new_status in dict(IncidentReport.STATUS_CHOICES):
            incident.status = new_status
            incident.reviewed_by = request.user
            incident.reviewed_at = timezone.now()
            incident.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'updated_at'])
            messages.success(request, 'Incident report updated.')
        return redirect('incident_reports:list')

    incidents = _scoped_incident_queryset(request.user)
    company_filter = request.GET.get('company', '')
    employee_filter = request.GET.get('employee', '')
    status_filter = request.GET.get('status', '')
    start_date = request.GET.get('start_date', '')
    end_date = request.GET.get('end_date', '')

    if company_filter:
        incidents = incidents.filter(company_id=company_filter)
    if employee_filter:
        incidents = incidents.filter(employee_id=employee_filter)
    if status_filter:
        incidents = incidents.filter(status=status_filter)
    else:
        incidents = incidents.filter(**INCIDENT_TAB_FILTERS[tab])
    if start_date:
        incidents = incidents.filter(incident_date__gte=start_date)
    if end_date:
        incidents = incidents.filter(incident_date__lte=end_date)

    mark_notifications_read(request.user, notification_type=Notification.TYPE_INCIDENT_REPORT)

    filter_employees = filter_queryset_by_user_companies(
        Employee.objects.select_related('company').order_by('last_name', 'first_name'),
        request.user,
    )

    return render(request, 'portal/manage_incidents.html', {
        'incidents': incidents,
        'company_filter': company_filter,
        'employee_filter': employee_filter,
        'status_filter': status_filter,
        'start_date_filter': start_date,
        'end_date_filter': end_date,
        'status_choices': IncidentReport.STATUS_CHOICES,
        'tab': tab,
        'tabs': [(key, label) for key, label, _filters in INCIDENT_TAB_DEFS],
        'filter_companies': get_accessible_companies(request.user).order_by('name'),
        'filter_employees': filter_employees,
    })
    """HR/admin view — incident reports scoped to accessible companies."""
@login_required
def manage_incident_detail(request, pk):
    _require_incident_report_access(request.user)

    incident = get_object_or_404(
        IncidentReport.objects.select_related('employee', 'company', 'reviewed_by'),
        pk=pk,
    )
    if not user_can_access_company(request.user, incident.company):
        raise PermissionDenied

    mark_notifications_read(request.user, content_object=incident)

    if request.method == 'POST':
        new_status = request.POST.get('status', incident.status)
        admin_notes = request.POST.get('admin_notes', incident.admin_notes)
        if new_status in dict(IncidentReport.STATUS_CHOICES):
            incident.status = new_status
            incident.admin_notes = admin_notes
            incident.reviewed_by = request.user
            incident.reviewed_at = timezone.now()
            incident.save(update_fields=[
                'status',
                'admin_notes',
                'reviewed_by',
                'reviewed_at',
                'updated_at',
            ])
            messages.success(request, 'Incident report updated.')
        return redirect('incident_reports:list')

    return render(request, 'portal/manage_incident_detail.html', {
        'incident': incident,
        'status_choices': IncidentReport.STATUS_CHOICES,
    })


@login_required
def portal_profile(request):
    employee, denial = _require_portal_employee(request)
    if denial:
        return denial

    if request.method == 'POST':
        if 'clear_photo' in request.POST:
            if employee.photo:
                employee.photo.delete(save=False)
            employee.photo = None
            employee.save(update_fields=['photo'])
            messages.success(request, 'Profile photo removed.')
            return redirect('portal:profile')

        uploaded = request.FILES.get('photo')
        if uploaded:
            try:
                validate_profile_image(uploaded)
            except ValidationError as exc:
                messages.error(request, '; '.join(exc.messages))
                return redirect('portal:profile')
            if employee.photo:
                employee.photo.delete(save=False)
            employee.photo = uploaded
            employee.save(update_fields=['photo'])
            messages.success(request, 'Profile photo updated.')
            return redirect('portal:profile')

        messages.error(request, 'Please choose a photo to upload.')
        return redirect('portal:profile')

    return render(request, 'portal/profile.html', {
        'employee': employee,
        'avatar': avatar_for_employee(employee),
    })
