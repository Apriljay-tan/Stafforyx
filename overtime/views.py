from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.company_access import (
    filter_queryset_by_user_companies,
    user_can_access_company,
)
from notifications.models import Notification
from notifications.services import mark_notifications_read

from .models import OvertimeRequest


def _require_hr(request):
    profile = getattr(request.user, 'stafforyx_profile', None)
    is_hr = request.user.is_superuser or (profile and profile.can_manage_employees)
    if not is_hr:
        raise PermissionDenied


@login_required
def manage_overtime(request):
    _require_hr(request)

    requests = filter_queryset_by_user_companies(
        OvertimeRequest.objects.select_related('employee', 'company').order_by('-date'),
        request.user,
    )

    status_filter = request.GET.get('status', '')
    date_filter = request.GET.get('date', '')
    employee_filter = request.GET.get('employee', '')

    if status_filter:
        requests = requests.filter(status=status_filter)
    if date_filter:
        requests = requests.filter(date=date_filter)
    if employee_filter:
        requests = requests.filter(employee_id=employee_filter)

    mark_notifications_read(request.user, notification_type=Notification.TYPE_OVERTIME_REQUEST)
    return render(request, 'overtime/manage_overtime.html', {
        'requests': requests,
        'status_filter': status_filter,
        'date_filter': date_filter,
        'employee_filter': employee_filter,
        'status_choices': OvertimeRequest.STATUS_CHOICES,
    })


@login_required
def manage_overtime_detail(request, pk):
    _require_hr(request)

    ot = get_object_or_404(
        OvertimeRequest.objects.select_related('employee', 'company'), pk=pk
    )
    if not user_can_access_company(request.user, ot.company):
        raise PermissionDenied
    mark_notifications_read(request.user, content_object=ot)

    if request.method == 'POST':
        action = request.POST.get('action')
        ot.manager_note = request.POST.get('manager_note', ot.manager_note)

        if action == 'approve':
            raw_hours = request.POST.get('approved_hours', '').strip()
            if raw_hours:
                from decimal import Decimal, InvalidOperation
                try:
                    ot.approved_hours = Decimal(raw_hours)
                except (InvalidOperation, ValueError):
                    messages.error(request, 'Invalid approved hours value.')
                    return redirect('overtime:manage_overtime_detail', pk=ot.pk)
            else:
                ot.approved_hours = ot.requested_hours
            ot.status = 'approved'
            ot.reviewed_by = request.user
            ot.reviewed_at = timezone.now()
            ot.save()
            messages.success(request, 'Overtime request approved.')

        elif action == 'reject':
            ot.status = 'rejected'
            ot.reviewed_by = request.user
            ot.reviewed_at = timezone.now()
            ot.save()
            messages.success(request, 'Overtime request rejected.')

        return redirect('overtime:manage_overtime')

    return render(request, 'overtime/manage_overtime_detail.html', {
        'ot': ot,
    })
