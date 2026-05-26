from datetime import date as _date, datetime as _datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from employees.models import Employee
from leaves.models import LeaveRequest

from .forms import AttendanceRecordForm, WorkScheduleForm
from .models import AttendanceRecord, WorkSchedule
from .services import compute_attendance


# ── helpers ───────────────────────────────────────────────────────────────────

_DAY_FIELDS = [
    'work_monday', 'work_tuesday', 'work_wednesday', 'work_thursday',
    'work_friday', 'work_saturday', 'work_sunday',
]


def _potential_absences_today():
    """
    Active employees with an active schedule, today is a scheduled workday,
    no attendance record exists yet for today, and not on approved leave.
    """
    today = _date.today()
    day_field = _DAY_FIELDS[today.weekday()]
    schedule_filter = {
        'work_schedule__isnull': False,
        'work_schedule__is_active': True,
        f'work_schedule__{day_field}': True,
        'status': 'active',
    }
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
        .select_related('work_schedule', 'department')
        .order_by('last_name', 'first_name')
    )


# ── Attendance CRUD ────────────────────────────────────────────────────────────

def attendance_list(request):
    records = AttendanceRecord.objects.select_related(
        'company', 'employee', 'employee__department', 'employee__position'
    )

    employee_id = request.GET.get('employee', '')
    if employee_id:
        records = records.filter(employee_id=employee_id)

    date = request.GET.get('date', '')
    if date:
        records = records.filter(date=date)

    status = request.GET.get('status', '')
    if status:
        records = records.filter(status=status)

    context = {
        'records': records,
        'employees': Employee.objects.all().order_by('last_name', 'first_name'),
        'employee_filter': employee_id,
        'date_filter': date,
        'status_filter': status,
        'status_choices': AttendanceRecord.STATUS_CHOICES,
        'potential_absences': _potential_absences_today(),
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
    records = (
        AttendanceRecord.objects
        .filter(date=today)
        .select_related('employee', 'employee__department')
        .order_by('-created_at')
    )
    data = []
    for r in records:
        data.append({
            'employee_id':   r.employee.employee_id,
            'employee_name': r.employee.full_name,
            'department':    r.employee.department.name if r.employee.department else '',
            'time_in':       r.time_in.strftime('%I:%M %p') if r.time_in else None,
            'time_out':      r.time_out.strftime('%I:%M %p') if r.time_out else None,
            'status':        r.computed_status or r.get_status_display(),
            'status_key':    r.computed_status or r.status,
            'total_hours':   str(r.total_hours),
        })
    return JsonResponse({'records': data, 'count': len(data)})


# ── Temporary phone/manual clock-in (dev/testing only) ────────────────────────

def attendance_clock(request):
    today = _date.today()
    employees = Employee.objects.filter(status='active').select_related(
        'company', 'department', 'work_schedule',
    ).order_by('last_name', 'first_name')

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
    schedules = WorkSchedule.objects.select_related('company').prefetch_related('employees')
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
    if request.method == 'POST':
        name = sched.name
        sched.delete()
        messages.success(request, f'Work schedule "{name}" deleted.')
        return redirect('attendance:schedule_list')
    return render(request, 'attendance/schedule_confirm_delete.html', {'sched': sched})
