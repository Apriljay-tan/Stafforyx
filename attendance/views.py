from datetime import date as _date, datetime as _datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from accounts.company_access import (
    filter_queryset_by_user_companies,
    get_accessible_companies,
    get_selected_company_from_request,
    user_can_access_company,
)
from employees.models import Employee
from leaves.models import LeaveRequest

from .forms import AttendanceLocationForm, AttendanceRecordForm, WorkScheduleForm
from .models import AttendanceLocation, AttendancePortalLog, AttendanceRecord, WorkSchedule
from .portal_services import can_employee_clock_from_request, get_client_ip
from .services import compute_attendance


# ── helpers ───────────────────────────────────────────────────────────────────

_DAY_FIELDS = [
    'work_monday', 'work_tuesday', 'work_wednesday', 'work_thursday',
    'work_friday', 'work_saturday', 'work_sunday',
]


def _potential_absences_today(company=None, accessible_companies_qs=None):
    """
    Active employees with an active schedule, today is a scheduled workday,
    no attendance record exists yet for today, and not on approved leave.

    company: filter to one specific Company object.
    accessible_companies_qs: filter to a queryset of companies (used when no
        single company is selected but access must still be restricted).
    """
    today = _date.today()
    day_field = _DAY_FIELDS[today.weekday()]
    schedule_filter = {
        'work_schedule__isnull': False,
        'work_schedule__is_active': True,
        f'work_schedule__{day_field}': True,
        'status': 'active',
    }
    if company is not None:
        schedule_filter['company'] = company
    elif accessible_companies_qs is not None:
        schedule_filter['company__in'] = accessible_companies_qs

    already_present = AttendanceRecord.objects.filter(date=today).values_list('employee_id', flat=True)
    on_approved_leave = LeaveRequest.objects.filter(
        status='approved',
        start_date__lte=today,
        end_date__gte=today,
    ).values_list('employee_id', flat=True)
    return (
        Employee.objects
        .filter(**schedule_filter)
        .exclude(id__in=already_present)
        .exclude(id__in=on_approved_leave)
        .select_related('work_schedule', 'department', 'company')
        .order_by('last_name', 'first_name')
    )


# ── Attendance CRUD ────────────────────────────────────────────────────────────

def attendance_list(request):
    selected_company = get_selected_company_from_request(request)
    accessible = get_accessible_companies(request.user)

    # Base queryset scoped to accessible companies
    records = filter_queryset_by_user_companies(
        AttendanceRecord.objects.select_related(
            'company', 'employee', 'employee__department', 'employee__position'
        ),
        request.user,
    )
    # Further narrow to selected company if one is chosen
    if selected_company:
        records = records.filter(company=selected_company)

    employee_id = request.GET.get('employee', '')
    if employee_id:
        records = records.filter(employee_id=employee_id)

    date = request.GET.get('date', '')
    if date:
        records = records.filter(date=date)

    status = request.GET.get('status', '')
    if status:
        records = records.filter(status=status)

    # Employee dropdown — scoped to selected company or all accessible
    employees_qs = filter_queryset_by_user_companies(
        Employee.objects.all(), request.user
    )
    if selected_company:
        employees_qs = employees_qs.filter(company=selected_company)
    employees_qs = employees_qs.order_by('last_name', 'first_name')

    # Potential absences — scoped to selected company or all accessible
    if selected_company:
        potential_absences = _potential_absences_today(company=selected_company)
    else:
        potential_absences = _potential_absences_today(accessible_companies_qs=accessible)

    # Show company column in live table when superuser views all companies
    show_company_column = (selected_company is None) and request.user.is_superuser

    context = {
        'records': records,
        'employees': employees_qs,
        'employee_filter': employee_id,
        'date_filter': date,
        'status_filter': status,
        'status_choices': AttendanceRecord.STATUS_CHOICES,
        'potential_absences': potential_absences,
        'selected_company': selected_company,
        'accessible_companies': accessible,
        'show_company_column': show_company_column,
    }
    return render(request, 'attendance/attendance_list.html', context)


def attendance_add(request):
    form = AttendanceRecordForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        record = form.save()
        compute_attendance(record)
        messages.success(request, 'Attendance record added successfully.')
        return redirect('attendance:attendance_list')
    return render(request, 'attendance/attendance_form.html', {
        'form': form,
        'action': 'Add',
    })


def attendance_edit(request, pk):
    record = get_object_or_404(
        AttendanceRecord.objects.select_related('employee', 'company'),
        pk=pk,
    )
    if not user_can_access_company(request.user, record.company):
        raise PermissionDenied
    form = AttendanceRecordForm(request.POST or None, instance=record)
    if request.method == 'POST' and form.is_valid():
        record = form.save()
        compute_attendance(record)
        messages.success(request, 'Attendance record updated successfully.')
        return redirect('attendance:attendance_list')
    return render(request, 'attendance/attendance_form.html', {
        'form': form,
        'record': record,
        'action': 'Edit',
    })


def attendance_delete(request, pk):
    record = get_object_or_404(
        AttendanceRecord.objects.select_related('employee', 'company'),
        pk=pk,
    )
    if not user_can_access_company(request.user, record.company):
        raise PermissionDenied
    if request.method == 'POST':
        employee_name = record.employee.full_name
        record_date = record.date
        record.delete()
        messages.success(
            request,
            f'Attendance record for {employee_name} on {record_date} has been deleted.',
        )
        return redirect('attendance:attendance_list')
    return render(request, 'attendance/attendance_confirm_delete.html', {'record': record})


# ── Today's live attendance JSON (for polling) ────────────────────────────────

def attendance_recent_json(request):
    today = _date.today()
    selected_company = get_selected_company_from_request(request)

    records = filter_queryset_by_user_companies(AttendanceRecord.objects.all(), request.user)
    if selected_company:
        records = records.filter(company=selected_company)

    records = (
        records
        .filter(date=today)
        .select_related('employee', 'employee__department', 'company')
        .order_by('-created_at')
    )

    show_company = (selected_company is None) and request.user.is_superuser
    data = []
    for r in records:
        entry = {
            'employee_id':   r.employee.employee_id,
            'employee_name': r.employee.full_name,
            'department':    r.employee.department.name if r.employee.department else '',
            'time_in':       r.time_in.strftime('%I:%M %p') if r.time_in else None,
            'time_out':      r.time_out.strftime('%I:%M %p') if r.time_out else None,
            'status':        r.computed_status or r.get_status_display(),
            'status_key':    r.computed_status or r.status,
            'total_hours':   str(r.total_hours),
        }
        if show_company:
            entry['company'] = r.company.name
        data.append(entry)
    return JsonResponse({'records': data, 'count': len(data), 'show_company': show_company})


# ── Temporary phone/manual clock-in (dev/testing only) ────────────────────────

def attendance_clock(request):
    today = _date.today()
    employees = (
        filter_queryset_by_user_companies(Employee.objects.filter(status='active'), request.user)
        .select_related('company', 'department', 'work_schedule')
        .order_by('last_name', 'first_name')
    )

    emp_pk = request.POST.get('employee') or request.GET.get('employee', '')
    selected_emp = None
    today_record = None

    if emp_pk:
        try:
            selected_emp = employees.get(pk=emp_pk)
            today_record = AttendanceRecord.objects.filter(
                employee=selected_emp, date=today
            ).first()
        except Employee.DoesNotExist:
            pass

    if request.method == 'POST':
        action = request.POST.get('action')

        if not selected_emp:
            messages.error(request, 'Please select an employee.')
            return redirect('attendance:attendance_clock')

        now_time = _datetime.now().time()

        if action == 'time_in':
            if today_record:
                messages.warning(request, f'{selected_emp.full_name} has already timed in today.')
            else:
                record = AttendanceRecord.objects.create(
                    company=selected_emp.company,
                    employee=selected_emp,
                    date=today,
                    time_in=now_time,
                    status='present',
                    remarks='Temporary phone/manual clock entry',
                )
                compute_attendance(record)
                messages.success(request, f'Time in recorded for {selected_emp.full_name}.')

        elif action == 'time_out':
            if not today_record or not today_record.time_in:
                messages.warning(request, 'Please time in first.')
            elif today_record.time_out:
                messages.warning(request, f'{selected_emp.full_name} has already timed out today.')
            else:
                today_record.time_out = now_time
                today_record.save(update_fields=['time_out'])
                compute_attendance(today_record)
                messages.success(request, f'Time out recorded for {selected_emp.full_name}.')

        return redirect(
            f"{reverse('attendance:attendance_clock')}?employee={selected_emp.pk}"
        )

    return render(request, 'attendance/attendance_clock.html', {
        'employees': employees,
        'selected_emp': selected_emp,
        'today_record': today_record,
        'today': today,
    })


# ── Work Schedule CRUD ─────────────────────────────────────────────────────────

def schedule_list(request):
    schedules = (
        filter_queryset_by_user_companies(WorkSchedule.objects.all(), request.user)
        .select_related('company')
        .prefetch_related('employees')
    )
    return render(request, 'attendance/schedule_list.html', {'schedules': schedules})


def schedule_add(request):
    form = WorkScheduleForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        sched = form.save()
        messages.success(request, f'Work schedule "{sched.name}" created.')
        return redirect('attendance:schedule_list')
    return render(request, 'attendance/schedule_form.html', {'form': form, 'action': 'Add'})


def schedule_edit(request, pk):
    sched = get_object_or_404(WorkSchedule, pk=pk)
    if not user_can_access_company(request.user, sched.company):
        raise PermissionDenied
    form = WorkScheduleForm(request.POST or None, instance=sched)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, f'Work schedule "{sched.name}" updated.')
        return redirect('attendance:schedule_list')
    return render(request, 'attendance/schedule_form.html', {
        'form': form, 'sched': sched, 'action': 'Edit',
    })


def schedule_delete(request, pk):
    sched = get_object_or_404(WorkSchedule, pk=pk)
    if not user_can_access_company(request.user, sched.company):
        raise PermissionDenied
    if request.method == 'POST':
        name = sched.name
        sched.delete()
        messages.success(request, f'Work schedule "{name}" deleted.')
        return redirect('attendance:schedule_list')
    return render(request, 'attendance/schedule_confirm_delete.html', {'sched': sched})


# ── Attendance Locations CRUD ──────────────────────────────────────────────────

def location_list(request):
    locations = (
        filter_queryset_by_user_companies(AttendanceLocation.objects.all(), request.user)
        .select_related('company')
        .order_by('company__name', 'name')
    )
    return render(request, 'attendance/location_list.html', {'locations': locations})


def location_add(request):
    accessible = get_accessible_companies(request.user)
    form = AttendanceLocationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        location = form.save(commit=False)
        if not user_can_access_company(request.user, location.company):
            raise PermissionDenied
        location.save()
        messages.success(request, f'Attendance location "{location.name}" created.')
        return redirect('attendance:location_list')
    # Restrict company choices to accessible companies
    form.fields['company'].queryset = accessible
    return render(request, 'attendance/location_form.html', {
        'form': form, 'action': 'Add',
    })


def location_edit(request, pk):
    location = get_object_or_404(AttendanceLocation.objects.select_related('company'), pk=pk)
    if not user_can_access_company(request.user, location.company):
        raise PermissionDenied
    accessible = get_accessible_companies(request.user)
    form = AttendanceLocationForm(request.POST or None, instance=location)
    form.fields['company'].queryset = accessible
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, f'Attendance location "{location.name}" updated.')
        return redirect('attendance:location_list')
    return render(request, 'attendance/location_form.html', {
        'form': form, 'location': location, 'action': 'Edit',
    })


def location_delete(request, pk):
    location = get_object_or_404(AttendanceLocation.objects.select_related('company'), pk=pk)
    if not user_can_access_company(request.user, location.company):
        raise PermissionDenied
    if request.method == 'POST':
        name = location.name
        location.delete()
        messages.success(request, f'Attendance location "{name}" deleted.')
        return redirect('attendance:location_list')
    return render(request, 'attendance/location_confirm_delete.html', {'location': location})


# ── Employee Attendance Portal (WiFi/IP-locked) ────────────────────────────────

def attendance_portal(request):
    """
    Employee self-service clock-in/out portal.

    The portal is locked to the employee's company network via public IP
    matching. If the request IP does not match any active AttendanceLocation
    for the employee's company, the clock buttons are blocked.

    Employee resolution:
      1. Employee.user OneToOneField (preferred)
      2. UserProfile.employee FK (fallback)
    """
    today = _date.today()

    # Resolve employee linked to this user
    employee = None
    try:
        employee = request.user.employee_profile  # Employee.user OneToOneField
    except Exception:
        pass

    if employee is None:
        profile = getattr(request.user, 'stafforyx_profile', None)
        if profile:
            employee = profile.employee

    if employee is None:
        return render(request, 'attendance/portal_no_employee.html', {
            'message': (
                'Your account is not linked to an employee record. '
                'Please contact your HR administrator.'
            ),
        })

    # IP check
    clock_check = can_employee_clock_from_request(request, employee)
    ip = clock_check['ip']
    allowed = clock_check['allowed']
    matched_location = clock_check['location']
    blocked_reason = clock_check['reason']

    today_record = AttendanceRecord.objects.filter(
        employee=employee, date=today
    ).first()

    # Log page open
    AttendancePortalLog.objects.create(
        company=employee.company,
        employee=employee,
        attendance_location=matched_location,
        action='page_open',
        ip_address=ip or None,
        user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
        status='allowed' if allowed else 'blocked',
        blocked_reason='' if allowed else blocked_reason,
    )

    if request.method == 'POST':
        action = request.POST.get('action')

        if not allowed:
            # Re-log blocked action attempt
            AttendancePortalLog.objects.create(
                company=employee.company,
                employee=employee,
                attendance_location=None,
                action=action if action in ('time_in', 'time_out') else 'blocked',
                ip_address=ip or None,
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
                status='blocked',
                blocked_reason=blocked_reason,
            )
            messages.error(request, blocked_reason)
            return redirect('attendance:attendance_portal')

        now_time = _datetime.now().time()
        record = None

        if action == 'time_in':
            if today_record:
                messages.warning(request, 'You have already timed in today.')
            else:
                record = AttendanceRecord.objects.create(
                    company=employee.company,
                    employee=employee,
                    date=today,
                    time_in=now_time,
                    status='present',
                    source='portal',
                    portal_location=matched_location,
                    remarks=f'Portal clock-in from {matched_location.name}',
                )
                compute_attendance(record)
                messages.success(request, f'Time in recorded at {now_time.strftime("%I:%M %p")}.')

        elif action == 'time_out':
            if not today_record or not today_record.time_in:
                messages.warning(request, 'You have not timed in yet today.')
            elif today_record.time_out:
                messages.warning(request, 'You have already timed out today.')
            else:
                today_record.time_out = now_time
                today_record.portal_location = today_record.portal_location or matched_location
                today_record.save(update_fields=['time_out', 'portal_location'])
                compute_attendance(today_record)
                record = today_record
                messages.success(request, f'Time out recorded at {now_time.strftime("%I:%M %p")}.')

        # Log the action result
        AttendancePortalLog.objects.create(
            company=employee.company,
            employee=employee,
            attendance_location=matched_location,
            attendance_record=record,
            action=action if action in ('time_in', 'time_out') else 'blocked',
            ip_address=ip or None,
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
            status='success' if record else 'failed',
            blocked_reason='',
        )
        return redirect('attendance:attendance_portal')

    return render(request, 'attendance/portal.html', {
        'employee': employee,
        'today': today,
        'today_record': today_record,
        'allowed': allowed,
        'ip': ip,
        'matched_location': matched_location,
        'blocked_reason': blocked_reason,
    })
