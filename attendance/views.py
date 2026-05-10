from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from employees.models import Employee

from .forms import AttendanceRecordForm
from .models import AttendanceRecord


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
    }
    return render(request, 'attendance/attendance_list.html', context)


def attendance_add(request):
    form = AttendanceRecordForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        record = form.save()
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
        form.save()
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
