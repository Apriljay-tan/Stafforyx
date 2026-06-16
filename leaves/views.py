from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.company_access import filter_queryset_by_user_companies, user_can_access_company
from employees.models import Employee
from notifications.models import Notification
from notifications.services import mark_notifications_read

from .forms import LeaveRequestForm, LeaveTypeForm
from .models import LeaveRequest, LeaveType


def leave_request_list(request):
    leave_requests = filter_queryset_by_user_companies(
        LeaveRequest.objects.select_related(
            'company', 'employee', 'employee__department', 'leave_type', 'reviewed_by'
        ),
        request.user,
    )

    employee_id = request.GET.get('employee', '')
    if employee_id:
        leave_requests = leave_requests.filter(employee_id=employee_id)

    leave_type_id = request.GET.get('leave_type', '')
    if leave_type_id:
        leave_requests = leave_requests.filter(leave_type_id=leave_type_id)

    status = request.GET.get('status', '')
    if status:
        leave_requests = leave_requests.filter(status=status)

    start_date = request.GET.get('start_date', '')
    if start_date:
        leave_requests = leave_requests.filter(start_date__gte=start_date)

    end_date = request.GET.get('end_date', '')
    if end_date:
        leave_requests = leave_requests.filter(end_date__lte=end_date)

    employees_qs = filter_queryset_by_user_companies(
        Employee.objects.all(), request.user
    ).order_by('last_name', 'first_name')
    leave_types_qs = filter_queryset_by_user_companies(
        LeaveType.objects.all(), request.user
    ).select_related('company')

    context = {
        'leave_requests': leave_requests,
        'employees': employees_qs,
        'leave_types': leave_types_qs,
        'employee_filter': employee_id,
        'leave_type_filter': leave_type_id,
        'status_filter': status,
        'start_date_filter': start_date,
        'end_date_filter': end_date,
        'status_choices': LeaveRequest.STATUS_CHOICES,
    }
    mark_notifications_read(request.user, notification_type=Notification.TYPE_LEAVE_REQUEST)
    return render(request, 'leaves/leave_request_list.html', context)


def leave_request_add(request):
    form = LeaveRequestForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        leave_request = form.save()
        messages.success(request, 'Leave request added successfully.')
        return redirect('leaves:leave_request_list')
    return render(request, 'leaves/leave_request_form.html', {
        'form': form,
        'action': 'Add',
    })


def leave_request_edit(request, pk):
    leave_request = get_object_or_404(
        LeaveRequest.objects.select_related('employee', 'leave_type', 'company'),
        pk=pk,
    )
    if not user_can_access_company(request.user, leave_request.company):
        raise PermissionDenied
    mark_notifications_read(request.user, content_object=leave_request)
    form = LeaveRequestForm(request.POST or None, instance=leave_request)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Leave request updated successfully.')
        return redirect('leaves:leave_request_list')
    return render(request, 'leaves/leave_request_form.html', {
        'form': form,
        'leave_request': leave_request,
        'action': 'Edit',
    })


def leave_request_delete(request, pk):
    leave_request = get_object_or_404(
        LeaveRequest.objects.select_related('employee', 'leave_type', 'company'),
        pk=pk,
    )
    if not user_can_access_company(request.user, leave_request.company):
        raise PermissionDenied
    if request.method == 'POST':
        employee_name = leave_request.employee.full_name
        leave_request.delete()
        messages.success(request, f'Leave request for {employee_name} has been deleted.')
        return redirect('leaves:leave_request_list')
    return render(request, 'leaves/leave_request_confirm_delete.html', {
        'leave_request': leave_request,
    })


def _review_leave_request(request, pk, status):
    leave_request = get_object_or_404(LeaveRequest.objects.select_related('company'), pk=pk)
    if not user_can_access_company(request.user, leave_request.company):
        raise PermissionDenied
    if request.method != 'POST':
        return redirect('leaves:leave_request_list')

    leave_request.status = status
    leave_request.reviewed_at = timezone.now()
    if request.user.is_authenticated:
        leave_request.reviewed_by = request.user
    leave_request.save(update_fields=['status', 'reviewed_at', 'reviewed_by', 'updated_at'])

    messages.success(request, f'Leave request {status}.')
    return redirect('leaves:leave_request_list')


def leave_request_approve(request, pk):
    return _review_leave_request(request, pk, 'approved')


def leave_request_reject(request, pk):
    return _review_leave_request(request, pk, 'rejected')


def leave_type_list(request):
    leave_types = (
        filter_queryset_by_user_companies(LeaveType.objects.all(), request.user)
        .select_related('company')
    )
    return render(request, 'leaves/leave_type_list.html', {'leave_types': leave_types})


def leave_type_add(request):
    form = LeaveTypeForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        leave_type = form.save()
        messages.success(request, f'Leave type "{leave_type.name}" created.')
        return redirect('leaves:leave_type_list')
    return render(request, 'leaves/leave_type_form.html', {
        'form': form,
        'action': 'Add',
    })


def leave_type_edit(request, pk):
    leave_type = get_object_or_404(LeaveType.objects.select_related('company'), pk=pk)
    if not user_can_access_company(request.user, leave_type.company):
        raise PermissionDenied
    form = LeaveTypeForm(request.POST or None, instance=leave_type)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Leave type updated successfully.')
        return redirect('leaves:leave_type_list')
    return render(request, 'leaves/leave_type_form.html', {
        'form': form,
        'leave_type': leave_type,
        'action': 'Edit',
    })


def leave_type_delete(request, pk):
    leave_type = get_object_or_404(LeaveType.objects.select_related('company'), pk=pk)
    if not user_can_access_company(request.user, leave_type.company):
        raise PermissionDenied
    if request.method == 'POST':
        name = leave_type.name
        leave_type.delete()
        messages.success(request, f'Leave type "{name}" has been deleted.')
        return redirect('leaves:leave_type_list')
    return render(request, 'leaves/leave_type_confirm_delete.html', {
        'leave_type': leave_type,
    })
