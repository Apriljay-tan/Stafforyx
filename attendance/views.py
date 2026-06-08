import base64
import binascii
import io
import mimetypes
import os
from datetime import date as _date, datetime as _datetime, timedelta as _timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from PIL import Image, UnidentifiedImageError

from accounts.company_access import (
    filter_queryset_by_user_companies,
    get_accessible_companies,
    get_selected_company_from_request,
    user_can_access_company,
)
from companies.models import Company
from employees.models import Employee
from leaves.models import LeaveRequest

from .forms import (
    AttendanceLocationForm, AttendanceRecordForm,
    BulkRosterForm, EmployeeDailyScheduleForm, ShiftTemplateForm, WorkScheduleForm,
)
from .models import (
    AttendanceLocation, AttendancePortalLog, AttendanceRecord,
    EmployeeDailySchedule, ShiftTemplate, WorkSchedule,
)
from .portal_services import can_employee_clock_from_request
from .schedule_services import resolve_expected_shift
from .services import compute_attendance


# â”€â”€ helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_DAY_FIELDS = [
    'work_monday', 'work_tuesday', 'work_wednesday', 'work_thursday',
    'work_friday', 'work_saturday', 'work_sunday',
]
_PORTAL_SELFIE_MAX_BYTES = 2 * 1024 * 1024
_PORTAL_ALLOWED_SELFIE_TYPES = {
    'image/jpeg': 'jpg',
    'image/png': 'png',
    'image/webp': 'webp',
}


def _parse_portal_decimal(value, *, field_name):
    if value in (None, ''):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f'Unable to read {field_name}. Please try again.')


def _parse_portal_gps_from_request(request):
    lat_raw = request.POST.get('gps_latitude')
    lon_raw = request.POST.get('gps_longitude')
    accuracy_raw = request.POST.get('gps_accuracy')

    if lat_raw in (None, '') and lon_raw in (None, '') and accuracy_raw in (None, ''):
        return None, None, None

    lat = _parse_portal_decimal(lat_raw, field_name='GPS latitude')
    lon = _parse_portal_decimal(lon_raw, field_name='GPS longitude')
    accuracy = _parse_portal_decimal(accuracy_raw, field_name='GPS accuracy')

    if lat is None or lon is None:
        raise ValueError('Location capture is incomplete. Please allow GPS and try again.')
    if lat < Decimal('-90') or lat > Decimal('90'):
        raise ValueError('Invalid GPS latitude received. Please recapture your location.')
    if lon < Decimal('-180') or lon > Decimal('180'):
        raise ValueError('Invalid GPS longitude received. Please recapture your location.')
    if accuracy is not None and accuracy < 0:
        raise ValueError('Invalid GPS accuracy received. Please recapture your location.')
    return lat, lon, accuracy


def _parse_portal_selfie_from_request(request):
    selfie_data = (request.POST.get('selfie_data') or '').strip()
    if not selfie_data:
        return None
    if not selfie_data.startswith('data:image/'):
        raise ValueError('Invalid selfie format. Please capture your selfie again.')

    try:
        header, encoded = selfie_data.split(',', 1)
    except ValueError:
        raise ValueError('Invalid selfie payload. Please capture your selfie again.')
    if ';base64' not in header:
        raise ValueError('Unsupported selfie encoding. Please capture your selfie again.')

    mime_type = header[5:].split(';', 1)[0].lower()
    ext = _PORTAL_ALLOWED_SELFIE_TYPES.get(mime_type)
    if not ext:
        raise ValueError('Selfie must be JPG, PNG, or WEBP.')

    try:
        image_bytes = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError('Selfie upload is corrupted. Please capture it again.')

    if not image_bytes:
        raise ValueError('Selfie image is empty. Please capture your selfie again.')
    if len(image_bytes) > _PORTAL_SELFIE_MAX_BYTES:
        raise ValueError('Selfie image is too large. Please capture a smaller image.')

    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            image.verify()
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        raise ValueError('Selfie image could not be validated. Please capture again.')

    filename = f'portal_selfie_{request.user.id}_{_datetime.now().strftime("%Y%m%d%H%M%S%f")}.{ext}'
    return ContentFile(image_bytes, name=filename)


def _potential_absences_today(company=None, accessible_companies_qs=None):
    """
    Active employees expected to work today with no attendance record yet and
    not on approved leave.

    Schedule resolution order (mirrors resolve_expected_shift):
      1. EmployeeDailySchedule for today â†’ not rest day
      2. Default WorkSchedule â†’ today is a scheduled weekday
      3. (No schedule â†’ excluded)

    company: filter to one specific Company object.
    accessible_companies_qs: filter to a queryset of companies.
    """
    from django.db.models import Q
    today = _date.today()
    day_field = _DAY_FIELDS[today.weekday()]

    # Company scope for daily schedules
    ds_filter = {'schedule_date': today, 'is_rest_day': False}
    ws_filter = {'work_schedule__isnull': False, 'work_schedule__is_active': True,
                 f'work_schedule__{day_field}': True}
    if company is not None:
        ds_filter['company'] = company
        ws_filter['company'] = company
    elif accessible_companies_qs is not None:
        ds_filter['company__in'] = accessible_companies_qs
        ws_filter['company__in'] = accessible_companies_qs

    # IDs with any daily schedule today (rest or not) â€” these override the work schedule
    has_daily_ids = set(
        EmployeeDailySchedule.objects.filter(
            schedule_date=today,
            **(({'company': company} if company else {'company__in': accessible_companies_qs})
               if (company or accessible_companies_qs is not None) else {})
        ).values_list('employee_id', flat=True)
    )

    # IDs scheduled via daily schedule (not rest day)
    active_daily_ids = set(
        EmployeeDailySchedule.objects.filter(**ds_filter)
        .values_list('employee_id', flat=True)
    )

    # IDs scheduled via work schedule but with no daily override
    ws_qs = Employee.objects.filter(status='active', **ws_filter).exclude(id__in=has_daily_ids)
    ws_ids = set(ws_qs.values_list('id', flat=True))

    flexible_qs = Employee.objects.filter(status='active').filter(
        Q(attendance_policy_type='flexible') | Q(flexible_schedule_enabled=True)
    )
    if company is not None:
        flexible_qs = flexible_qs.filter(company=company)
    elif accessible_companies_qs is not None:
        flexible_qs = flexible_qs.filter(company__in=accessible_companies_qs)
    flexible_ids = {
        emp.id for emp in flexible_qs
        if not emp.is_flexible_day_off(today)
    }

    scheduled_ids = active_daily_ids | ws_ids | flexible_ids

    already_present = AttendanceRecord.objects.filter(date=today).values_list('employee_id', flat=True)
    on_approved_leave = LeaveRequest.objects.filter(
        status='approved',
        start_date__lte=today,
        end_date__gte=today,
    ).values_list('employee_id', flat=True)

    base_filter = {'status': 'active', 'id__in': scheduled_ids}
    if company is not None:
        base_filter['company'] = company
    elif accessible_companies_qs is not None:
        base_filter['company__in'] = accessible_companies_qs

    return (
        Employee.objects
        .filter(**base_filter)
        .exclude(id__in=already_present)
        .exclude(id__in=on_approved_leave)
        .select_related('work_schedule', 'department', 'company')
        .order_by('last_name', 'first_name')
    )


# â”€â”€ Attendance CRUD â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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

    # Employee dropdown â€” scoped to selected company or all accessible
    employees_qs = filter_queryset_by_user_companies(
        Employee.objects.all(), request.user
    )
    if selected_company:
        employees_qs = employees_qs.filter(company=selected_company)
    employees_qs = employees_qs.order_by('last_name', 'first_name')

    # Potential absences â€” scoped to selected company or all accessible
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


# â”€â”€ Today's live attendance JSON (for polling) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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


# â”€â”€ Temporary phone/manual clock-in (dev/testing only) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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


# â”€â”€ Work Schedule CRUD â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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


# â”€â”€ Attendance Locations CRUD â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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


# â”€â”€ Shift Templates CRUD â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def shift_list(request):
    shifts = (
        filter_queryset_by_user_companies(ShiftTemplate.objects.all(), request.user)
        .select_related('company')
    )
    return render(request, 'attendance/shift_list.html', {'shifts': shifts})


def shift_add(request):
    accessible = get_accessible_companies(request.user)
    form = ShiftTemplateForm(request.POST or None)
    form.fields['company'].queryset = accessible
    if request.method == 'POST' and form.is_valid():
        shift = form.save(commit=False)
        if not user_can_access_company(request.user, shift.company):
            raise PermissionDenied
        shift.save()
        messages.success(request, f'Shift template "{shift.name}" created.')
        return redirect('attendance:shift_list')
    return render(request, 'attendance/shift_form.html', {'form': form, 'action': 'Add'})


def shift_edit(request, pk):
    shift = get_object_or_404(ShiftTemplate.objects.select_related('company'), pk=pk)
    if not user_can_access_company(request.user, shift.company):
        raise PermissionDenied
    accessible = get_accessible_companies(request.user)
    form = ShiftTemplateForm(request.POST or None, instance=shift)
    form.fields['company'].queryset = accessible
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, f'Shift template "{shift.name}" updated.')
        return redirect('attendance:shift_list')
    return render(request, 'attendance/shift_form.html', {
        'form': form, 'shift': shift, 'action': 'Edit',
    })


def shift_delete(request, pk):
    shift = get_object_or_404(ShiftTemplate.objects.select_related('company'), pk=pk)
    if not user_can_access_company(request.user, shift.company):
        raise PermissionDenied
    if request.method == 'POST':
        name = shift.name
        shift.delete()
        messages.success(request, f'Shift template "{name}" deleted.')
        return redirect('attendance:shift_list')
    return render(request, 'attendance/shift_confirm_delete.html', {'shift': shift})


# â”€â”€ Employee Daily Schedules CRUD + Bulk Generator â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def employee_schedule_list(request):
    accessible = get_accessible_companies(request.user)
    selected_company = get_selected_company_from_request(request)

    qs = filter_queryset_by_user_companies(
        EmployeeDailySchedule.objects.select_related(
            'employee', 'company', 'shift_template', 'created_by'
        ),
        request.user,
    )
    if selected_company:
        qs = qs.filter(company=selected_company)

    # Filters from GET
    date_filter = request.GET.get('date', '')
    emp_filter = request.GET.get('employee', '')
    source_filter = request.GET.get('source', '')

    if date_filter:
        qs = qs.filter(schedule_date=date_filter)
    if emp_filter:
        qs = qs.filter(employee_id=emp_filter)
    if source_filter:
        qs = qs.filter(source=source_filter)

    qs = qs.order_by('-schedule_date', 'employee__last_name')

    employees_qs = filter_queryset_by_user_companies(Employee.objects.all(), request.user)
    if selected_company:
        employees_qs = employees_qs.filter(company=selected_company)

    return render(request, 'attendance/employee_schedule_list.html', {
        'schedules': qs,
        'employees': employees_qs.order_by('last_name', 'first_name'),
        'date_filter': date_filter,
        'emp_filter': emp_filter,
        'source_filter': source_filter,
        'source_choices': EmployeeDailySchedule.SOURCE_CHOICES,
        'selected_company': selected_company,
    })


def employee_schedule_add(request):
    accessible = get_accessible_companies(request.user)
    form = EmployeeDailyScheduleForm(request.POST or None)
    form.fields['company'].queryset = accessible
    form.fields['employee'].queryset = filter_queryset_by_user_companies(
        Employee.objects.all(), request.user
    ).order_by('last_name', 'first_name')
    form.fields['shift_template'].queryset = filter_queryset_by_user_companies(
        ShiftTemplate.objects.filter(is_active=True), request.user
    )
    if request.method == 'POST' and form.is_valid():
        ds = form.save(commit=False)
        if not user_can_access_company(request.user, ds.company):
            raise PermissionDenied
        ds.created_by = request.user
        ds.save()
        messages.success(request, f'Schedule for {ds.employee.full_name} on {ds.schedule_date} saved.')
        return redirect('attendance:employee_schedule_list')
    return render(request, 'attendance/employee_schedule_form.html', {
        'form': form, 'action': 'Add',
    })


def employee_schedule_edit(request, pk):
    ds = get_object_or_404(
        EmployeeDailySchedule.objects.select_related('employee', 'company'), pk=pk
    )
    if not user_can_access_company(request.user, ds.company):
        raise PermissionDenied
    accessible = get_accessible_companies(request.user)
    form = EmployeeDailyScheduleForm(request.POST or None, instance=ds)
    form.fields['company'].queryset = accessible
    form.fields['employee'].queryset = filter_queryset_by_user_companies(
        Employee.objects.all(), request.user
    ).order_by('last_name', 'first_name')
    form.fields['shift_template'].queryset = filter_queryset_by_user_companies(
        ShiftTemplate.objects.filter(is_active=True), request.user
    )
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, f'Schedule for {ds.employee.full_name} on {ds.schedule_date} updated.')
        return redirect('attendance:employee_schedule_list')
    return render(request, 'attendance/employee_schedule_form.html', {
        'form': form, 'ds': ds, 'action': 'Edit',
    })


def employee_schedule_delete(request, pk):
    ds = get_object_or_404(
        EmployeeDailySchedule.objects.select_related('employee', 'company'), pk=pk
    )
    if not user_can_access_company(request.user, ds.company):
        raise PermissionDenied
    if request.method == 'POST':
        label = f'{ds.employee.full_name} on {ds.schedule_date}'
        ds.delete()
        messages.success(request, f'Schedule for {label} deleted.')
        return redirect('attendance:employee_schedule_list')
    return render(request, 'attendance/employee_schedule_confirm_delete.html', {'ds': ds})


def employee_schedule_bulk(request):
    """Bulk roster generator â€” assign a shift to employees over a date range."""
    import datetime as _dt
    accessible = get_accessible_companies(request.user)
    form = BulkRosterForm(request.POST or None, accessible_companies=accessible)

    if request.method == 'POST' and form.is_valid():
        company = form.cleaned_data['company']
        if not user_can_access_company(request.user, company):
            raise PermissionDenied

        shift = form.cleaned_data['shift_template']
        date_from = form.cleaned_data['date_from']
        date_to = form.cleaned_data['date_to']
        weekdays = [int(d) for d in form.cleaned_data.get('weekdays', [])]
        overwrite = form.cleaned_data.get('overwrite_existing', False)

        employees = Employee.objects.filter(company=company, status='active')
        created = updated = skipped = 0

        current = date_from
        while current <= date_to:
            if not weekdays or current.weekday() in weekdays:
                for emp in employees:
                    if overwrite:
                        obj, was_created = EmployeeDailySchedule.objects.update_or_create(
                            employee=emp,
                            schedule_date=current,
                            defaults=dict(
                                company=company,
                                shift_template=shift,
                                is_rest_day=False,
                                source='generated',
                                created_by=request.user,
                            ),
                        )
                        if was_created:
                            created += 1
                        else:
                            updated += 1
                    else:
                        if not EmployeeDailySchedule.objects.filter(
                            employee=emp, schedule_date=current
                        ).exists():
                            EmployeeDailySchedule.objects.create(
                                company=company,
                                employee=emp,
                                schedule_date=current,
                                shift_template=shift,
                                is_rest_day=False,
                                source='generated',
                                created_by=request.user,
                            )
                            created += 1
                        else:
                            skipped += 1
            current += _dt.timedelta(days=1)

        messages.success(
            request,
            f'Roster generated: {created} created, {updated} updated, {skipped} skipped.'
        )
        return redirect('attendance:employee_schedule_list')

    return render(request, 'attendance/employee_schedule_bulk.html', {
        'form': form,
    })


# â”€â”€ Employee Attendance Portal (WiFi/IP-locked) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _get_company_portal_log_setting(company, field_name, default):
    if company is None:
        return default
    value = getattr(company, field_name, default)
    return default if value is None else value


def _should_log_page_opened(company):
    return bool(_get_company_portal_log_setting(company, 'attendance_log_page_opened_events', False))


def _should_log_blocked_attempts(company):
    return bool(_get_company_portal_log_setting(company, 'attendance_log_blocked_attempts', True))


def _should_log_clock_actions(company):
    return bool(_get_company_portal_log_setting(company, 'attendance_log_clock_actions', True))


def _scoped_portal_logs_for_user(user):
    return filter_queryset_by_user_companies(
        AttendancePortalLog.objects.select_related(
            'company', 'employee', 'employee__department',
            'attendance_location', 'attendance_record',
        ),
        user,
    )


def _delete_portal_log_queryset(queryset):
    if queryset is None:
        return 0
    to_delete_ids = list(queryset.values_list('pk', flat=True))
    if not to_delete_ids:
        return 0
    deleted_total, breakdown = queryset.delete()
    return breakdown.get('attendance.AttendancePortalLog', 0) or min(deleted_total, len(to_delete_ids))


def _resolve_cleanup_target_company(request):
    company_id_raw = (request.POST.get('target_company_id') or '').strip()
    if not company_id_raw:
        return None
    try:
        company_id = int(company_id_raw)
    except (TypeError, ValueError):
        return None
    company = get_object_or_404(Company, pk=company_id)
    if not user_can_access_company(request.user, company):
        raise PermissionDenied
    return company


def _apply_portal_log_filters(logs, request):
    company_filter = request.GET.get('company', '').strip()
    if company_filter:
        logs = logs.filter(company_id=company_filter)

    action_filter = request.GET.get('action', '').strip()
    valid_actions = {choice[0] for choice in AttendancePortalLog.ACTION_CHOICES}
    if action_filter in valid_actions:
        logs = logs.filter(action=action_filter)

    selfie_filter = request.GET.get('selfie', '').strip().lower()
    if selfie_filter == 'yes':
        logs = logs.filter(selfie_image__isnull=False).exclude(selfie_image='')
    elif selfie_filter == 'no':
        logs = logs.filter(Q(selfie_image__isnull=True) | Q(selfie_image=''))

    employee_filter = request.GET.get('employee', '').strip()
    if employee_filter:
        logs = logs.filter(employee_id=employee_filter)

    date_from_filter = request.GET.get('date_from', '').strip()
    parsed_date_from = parse_date(date_from_filter) if date_from_filter else None
    if parsed_date_from is not None:
        logs = logs.filter(created_at__date__gte=parsed_date_from)

    date_to_filter = request.GET.get('date_to', '').strip()
    parsed_date_to = parse_date(date_to_filter) if date_to_filter else None
    if parsed_date_to is not None:
        logs = logs.filter(created_at__date__lte=parsed_date_to)

    return logs, {
        'employee_filter': employee_filter,
        'company_filter': company_filter,
        'action_filter': action_filter,
        'selfie_filter': selfie_filter,
        'date_from_filter': date_from_filter,
        'date_to_filter': date_to_filter,
    }


def portal_log_list(request):
    selected_company = get_selected_company_from_request(request)
    accessible_companies = get_accessible_companies(request.user)

    base_logs = _scoped_portal_logs_for_user(request.user)

    if request.method == 'POST':
        bulk_action = (request.POST.get('bulk_action') or '').strip()

        if bulk_action == 'delete_selected':
            selected_ids = request.POST.getlist('selected_log_ids')
            logs_to_delete = base_logs.filter(pk__in=selected_ids)
            deleted_count = _delete_portal_log_queryset(logs_to_delete)
            if deleted_count:
                messages.success(request, f'Deleted {deleted_count} selected portal log(s).')
            else:
                messages.warning(request, 'No portal logs were selected for deletion.')

        elif bulk_action == 'delete_page_opened_for_company':
            target_company = _resolve_cleanup_target_company(request)
            if target_company is None:
                messages.error(request, 'Select a company before deleting page-opened logs.')
            else:
                logs_to_delete = base_logs.filter(company=target_company, action='page_open')
                deleted_count = _delete_portal_log_queryset(logs_to_delete)
                messages.success(
                    request,
                    f'Deleted {deleted_count} page-opened portal log(s) for {target_company.name}.',
                )

        elif bulk_action == 'delete_older_than_days':
            raw_days = (request.POST.get('older_than_days') or '').strip()
            try:
                older_than_days = int(raw_days)
            except (TypeError, ValueError):
                older_than_days = 0

            if older_than_days < 1:
                messages.error(request, 'Days must be a whole number greater than or equal to 1.')
            else:
                cutoff = timezone.now() - _timedelta(days=older_than_days)
                logs_to_delete = base_logs.filter(created_at__lt=cutoff)
                target_company = _resolve_cleanup_target_company(request)
                if target_company is not None:
                    logs_to_delete = logs_to_delete.filter(company=target_company)

                deleted_count = _delete_portal_log_queryset(logs_to_delete)
                if target_company is not None:
                    messages.success(
                        request,
                        f'Deleted {deleted_count} portal log(s) older than {older_than_days} day(s) for {target_company.name}.',
                    )
                else:
                    messages.success(
                        request,
                        f'Deleted {deleted_count} portal log(s) older than {older_than_days} day(s).',
                    )

        elif bulk_action == 'delete_all_for_company':
            target_company = _resolve_cleanup_target_company(request)
            if target_company is None:
                messages.error(request, 'Select a company before using wipeout.')
            else:
                return redirect('attendance:portal_log_delete_all_company_confirm', company_id=target_company.pk)

        else:
            messages.error(request, 'Unknown cleanup action requested.')

        return redirect('attendance:portal_log_list')

    logs = base_logs.order_by('-created_at')

    if selected_company:
        logs = logs.filter(company=selected_company)

    logs, active_filters = _apply_portal_log_filters(logs, request)

    paginator = Paginator(logs, 50)
    page_obj = paginator.get_page(request.GET.get('page'))

    employees = (
        Employee.objects
        .filter(id__in=logs.values_list('employee_id', flat=True))
        .order_by('last_name', 'first_name')
        .distinct()
    )

    return render(request, 'attendance/portal_log_list.html', {
        'page_obj': page_obj,
        'logs': page_obj.object_list,
        'selected_company': selected_company,
        'accessible_companies': accessible_companies,
        'action_choices': AttendancePortalLog.ACTION_CHOICES,
        'employees': employees,
        **active_filters,
    })


def portal_log_delete_all_company_confirm(request, company_id):
    company = get_object_or_404(Company, pk=company_id)
    if not user_can_access_company(request.user, company):
        raise PermissionDenied

    scoped_logs = _scoped_portal_logs_for_user(request.user).filter(company=company)
    if request.method == 'POST':
        confirm_text = (request.POST.get('confirm_text') or '').strip()
        if confirm_text != company.name:
            messages.error(request, 'Confirmation text does not match company name.')
            return redirect('attendance:portal_log_delete_all_company_confirm', company_id=company.pk)

        deleted_count = _delete_portal_log_queryset(scoped_logs)
        messages.success(request, f'Wipeout complete: deleted {deleted_count} portal log(s) for {company.name}.')
        return redirect('attendance:portal_log_list')

    return render(request, 'attendance/portal_log_wipeout_confirm.html', {
        'company': company,
        'log_count': scoped_logs.count(),
    })


def portal_log_detail(request, pk):
    log = get_object_or_404(_scoped_portal_logs_for_user(request.user), pk=pk)
    return render(request, 'attendance/portal_log_detail.html', {
        'log': log,
    })


def portal_log_selfie(request, pk):
    log = get_object_or_404(_scoped_portal_logs_for_user(request.user), pk=pk)
    if not log.selfie_image:
        raise Http404('No selfie is stored for this attendance portal log.')

    storage = log.selfie_image.storage
    selfie_name = log.selfie_image.name
    if not storage.exists(selfie_name):
        raise Http404('Selfie file is no longer available.')

    content_type, _ = mimetypes.guess_type(selfie_name)
    return FileResponse(
        storage.open(selfie_name, 'rb'),
        content_type=content_type or 'application/octet-stream',
        as_attachment=False,
        filename=os.path.basename(selfie_name),
    )


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
    ip_allowed = clock_check['allowed']
    matched_location = clock_check['location']
    ip_blocked_reason = clock_check['reason']
    locations_checked = clock_check['locations_checked']
    allow_other_registered_locations = clock_check['allow_other_registered_locations']
    ip_validation_enabled = clock_check['ip_validation_enabled']
    company_require_gps = clock_check['company_require_gps']
    company_require_selfie = clock_check['company_require_selfie']

    # Record lookup — must precede the schedule/allowed check so that an open
    # overnight carry-over record can influence whether time-out is permitted
    # (e.g. when today happens to be a scheduled rest day).
    today_record = AttendanceRecord.objects.filter(
        employee=employee, date=today
    ).first()

    carry_over_record = None
    if today_record is None:
        yesterday = today - _timedelta(days=1)
        carry_over_record = AttendanceRecord.objects.filter(
            employee=employee,
            date=yesterday,
            time_in__isnull=False,
            time_out__isnull=True,
        ).first()

    # The record shown/used on the portal: today's record if it exists, else
    # yesterday's incomplete (carry-over) record so overnight workers can time out.
    display_record = today_record or carry_over_record

    # Schedule check — always evaluated against today's date for new time-ins.
    shift_info = resolve_expected_shift(employee, today)
    is_flexible_schedule = employee.uses_flexible_attendance_policy
    flexible_day_off_today = (
        employee.is_flexible_day_off(today) if is_flexible_schedule else False
    )
    schedule_allowed = shift_info['scheduled']
    schedule_blocked_reason = ''
    if not schedule_allowed:
        if shift_info['is_rest_day']:
            schedule_blocked_reason = 'Today is marked as a rest day. Contact HR if this is incorrect.'
        else:
            schedule_blocked_reason = 'No schedule assigned for today. Please contact HR.'

    if ip_validation_enabled:
        require_selfie = bool(matched_location and matched_location.require_selfie)
        require_gps = bool(matched_location and matched_location.require_gps)
    else:
        require_selfie = company_require_selfie
        require_gps = company_require_gps

    # allowed for time-in: IP + schedule must both pass.
    # allowed for time-out: IP must pass; schedule block is lifted when an open
    # overnight carry-over record exists (the shift started in a prior day that
    # was scheduled — blocking time-out now would strand the record open).
    # A single `allowed` flag covers both buttons; the template disables the
    # time-in button separately when a record already has time_in set.
    has_open_carry_over = carry_over_record is not None
    allowed = ip_allowed and (schedule_allowed or has_open_carry_over)
    if not ip_allowed:
        blocked_reason = ip_blocked_reason
    elif not schedule_allowed and not has_open_carry_over:
        blocked_reason = schedule_blocked_reason
    else:
        blocked_reason = ''

    # Determine which validation path is active for audit logging.
    if not ip_validation_enabled:
        validation_method = 'IP_DISABLED_GPS_SELFIE'
    elif ip_allowed:
        validation_method = 'IP'
    else:
        validation_method = 'BLOCKED'

    user_agent = request.META.get('HTTP_USER_AGENT', '')[:500]
    log_page_opened = _should_log_page_opened(employee.company)
    log_blocked_attempts = _should_log_blocked_attempts(employee.company)
    log_clock_actions = _should_log_clock_actions(employee.company)

    # Log page open
    if log_page_opened:
        AttendancePortalLog.objects.create(
            company=employee.company,
            employee=employee,
            attendance_location=matched_location,
            action='page_open',
            ip_address=ip or None,
            user_agent=user_agent,
            status='allowed' if allowed else 'blocked',
            blocked_reason='' if allowed else blocked_reason,
            validation_method=validation_method,
        )

    if request.method == 'POST':
        action = request.POST.get('action')
        action_key = action if action in ('time_in', 'time_out') else 'blocked'
        gps_latitude = gps_longitude = gps_accuracy = None
        selfie_image = None
        gps_error = ''
        selfie_error = ''

        if request.POST.get('gps_latitude') or request.POST.get('gps_longitude') or request.POST.get('gps_accuracy'):
            try:
                gps_latitude, gps_longitude, gps_accuracy = _parse_portal_gps_from_request(request)
            except ValueError as exc:
                gps_error = str(exc)

        if request.POST.get('selfie_data'):
            try:
                selfie_image = _parse_portal_selfie_from_request(request)
            except ValueError as exc:
                selfie_error = str(exc)

        if not allowed:
            if log_blocked_attempts:
                AttendancePortalLog.objects.create(
                    company=employee.company,
                    employee=employee,
                    attendance_location=matched_location,
                    action=action_key,
                    ip_address=ip or None,
                    user_agent=user_agent,
                    status='blocked',
                    blocked_reason=blocked_reason,
                    gps_latitude=gps_latitude,
                    gps_longitude=gps_longitude,
                    gps_accuracy=gps_accuracy,
                    selfie_image=selfie_image,
                    validation_method='BLOCKED',
                )
            messages.error(request, blocked_reason)
            return redirect('attendance:attendance_portal')

        verification_error = ''
        if require_selfie and not selfie_image:
            verification_error = selfie_error or (
                'This location requires a selfie before you can time in or time out.'
            )
        elif require_gps and (gps_latitude is None or gps_longitude is None):
            verification_error = gps_error or (
                'This location requires GPS permission before you can time in or time out.'
            )

        if verification_error:
            if log_blocked_attempts:
                AttendancePortalLog.objects.create(
                    company=employee.company,
                    employee=employee,
                    attendance_location=matched_location,
                    action=action_key,
                    ip_address=ip or None,
                    user_agent=user_agent,
                    status='blocked',
                    blocked_reason=verification_error,
                    gps_latitude=gps_latitude,
                    gps_longitude=gps_longitude,
                    gps_accuracy=gps_accuracy,
                    selfie_image=selfie_image,
                    validation_method='BLOCKED',
                )
            messages.error(request, verification_error)
            return redirect('attendance:attendance_portal')

        now_time = _datetime.now().time()
        record = None

        if action == 'time_in':
            if today_record:
                messages.warning(request, 'You have already timed in today.')
            elif carry_over_record:
                # Prevent a new time-in while an overnight shift is still open
                messages.warning(
                    request,
                    'You still have an open shift from the previous day. '
                    'Please time out first before timing in again.',
                )
            else:
                record = AttendanceRecord.objects.create(
                    company=employee.company,
                    employee=employee,
                    date=today,
                    time_in=now_time,
                    break_minutes=(
                        employee.default_break_minutes
                        if employee.uses_flexible_attendance_policy
                        else 0
                    ),
                    status='present',
                    source='portal',
                    portal_location=matched_location,
                    remarks=(
                        f'Portal clock-in from {matched_location.name}'
                        if matched_location else 'Portal clock-in (IP validation disabled)'
                    ),
                )
                compute_attendance(record)
                messages.success(request, f'Time in recorded at {now_time.strftime("%I:%M %p")}.')

        elif action == 'time_out':
            # Use today's record; fall back to yesterday's incomplete (overnight) record
            target_record = today_record or carry_over_record
            if not target_record or not target_record.time_in:
                messages.warning(request, 'You have not timed in yet today.')
            elif target_record.time_out:
                messages.warning(request, 'You have already timed out today.')
            else:
                target_record.time_out = now_time
                target_record.portal_location = target_record.portal_location or matched_location
                target_record.save(update_fields=['time_out', 'portal_location'])
                compute_attendance(target_record)
                record = target_record
                messages.success(request, f'Time out recorded at {now_time.strftime("%I:%M %p")}.')

        # Log the action result
        if log_clock_actions:
            AttendancePortalLog.objects.create(
                company=employee.company,
                employee=employee,
                attendance_location=matched_location,
                attendance_record=record,
                action=action_key,
                ip_address=ip or None,
                user_agent=user_agent,
                status='success' if record else 'failed',
                blocked_reason='',
                gps_latitude=gps_latitude,
                gps_longitude=gps_longitude,
                gps_accuracy=gps_accuracy,
                selfie_image=selfie_image,
                validation_method=validation_method,
            )
        return redirect('attendance:attendance_portal')

    if not display_record or not display_record.time_in:
        clock_state = 'not_timed_in'
    elif display_record.time_out:
        clock_state = 'timed_out'
    else:
        clock_state = 'timed_in'

    return render(request, 'attendance/portal.html', {
        'employee': employee,
        'today': today,
        'today_record': display_record,
        'carry_over': carry_over_record is not None,
        'allowed': allowed,
        'ip': ip,
        'ip_allowed': ip_allowed,
        'matched_location': matched_location,
        'blocked_reason': blocked_reason,
        'locations_checked': locations_checked,
        'allow_other_registered_locations': allow_other_registered_locations,
        'ip_validation_enabled': ip_validation_enabled,
        'shift_info': shift_info,
        'is_flexible_schedule': is_flexible_schedule,
        'flexible_day_off_today': flexible_day_off_today,
        'schedule_allowed': schedule_allowed,
        'schedule_blocked_reason': schedule_blocked_reason,
        'require_selfie': require_selfie,
        'require_gps': require_gps,
        'clock_state': clock_state,
    })

