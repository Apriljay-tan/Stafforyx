from decimal import Decimal, InvalidOperation

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


def _refresh_draft_payroll_for_overtime_requests(overtime_requests):
    from payroll.models import PayrollPeriod
    from payroll.services import generate_payroll_for_period

    seen_period_ids = set()
    for ot in overtime_requests:
        periods = PayrollPeriod.objects.filter(
            company=ot.company,
            start_date__lte=ot.date,
            end_date__gte=ot.date,
        )
        for period in periods:
            if period.pk in seen_period_ids:
                continue
            generate_payroll_for_period(period, allow_update_draft=True)
            seen_period_ids.add(period.pk)


def _approve_overtime_request(ot, user, approved_hours=None, manager_note=None):
    if approved_hours is None:
        approved_hours = ot.requested_hours
    ot.approved_hours = approved_hours
    if manager_note is not None:
        ot.manager_note = manager_note
    ot.status = 'approved'
    ot.reviewed_by = user
    ot.reviewed_at = timezone.now()
    ot.save()


def _reject_overtime_request(ot, user, manager_note=None):
    if manager_note is not None:
        ot.manager_note = manager_note
    ot.status = 'rejected'
    ot.reviewed_by = user
    ot.reviewed_at = timezone.now()
    ot.save()


@login_required
def manage_overtime(request):
    _require_hr(request)

    requests = filter_queryset_by_user_companies(
        OvertimeRequest.objects.select_related('employee', 'company').order_by('-date'),
        request.user,
    )

    if request.method == 'POST':
        selected_ids = request.POST.getlist('selected_requests')
        bulk_action = request.POST.get('bulk_action', '')
        bulk_note = request.POST.get('bulk_manager_note', '')
        bulk_note = bulk_note.strip()

        if not selected_ids:
            messages.warning(request, 'Select at least one overtime request.')
            return redirect(request.get_full_path())

        selected = list(
            requests
            .filter(pk__in=selected_ids, status='pending')
            .select_related('employee', 'company')
        )
        skipped = len(selected_ids) - len(selected)

        if not selected:
            messages.warning(request, 'No pending overtime requests were selected.')
            return redirect(request.get_full_path())

        if bulk_action == 'approve':
            for ot in selected:
                _approve_overtime_request(
                    ot,
                    request.user,
                    approved_hours=ot.requested_hours,
                    manager_note=bulk_note,
                )
            _refresh_draft_payroll_for_overtime_requests(selected)
            message = f'Approved {len(selected)} overtime request(s).'
        elif bulk_action == 'reject':
            for ot in selected:
                _reject_overtime_request(ot, request.user, manager_note=bulk_note)
            message = f'Rejected {len(selected)} overtime request(s).'
        else:
            messages.warning(request, 'Choose a bulk action.')
            return redirect(request.get_full_path())

        if skipped:
            message += f' Skipped {skipped} non-pending or inaccessible request(s).'
        messages.success(request, message)
        return redirect(request.get_full_path())

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
                try:
                    approved_hours = Decimal(raw_hours)
                except (InvalidOperation, ValueError):
                    messages.error(request, 'Invalid approved hours value.')
                    return redirect('overtime:manage_overtime_detail', pk=ot.pk)
            else:
                approved_hours = ot.requested_hours
            _approve_overtime_request(
                ot,
                request.user,
                approved_hours=approved_hours,
                manager_note=ot.manager_note,
            )
            _refresh_draft_payroll_for_overtime_requests([ot])

            messages.success(request, 'Overtime request approved.')

        elif action == 'reject':
            _reject_overtime_request(ot, request.user, manager_note=ot.manager_note)
            messages.success(request, 'Overtime request rejected.')

        return redirect('overtime:manage_overtime')

    return render(request, 'overtime/manage_overtime_detail.html', {
        'ot': ot,
    })
