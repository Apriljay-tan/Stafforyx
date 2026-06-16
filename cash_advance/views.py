from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from accounts.company_access import (
    filter_queryset_by_user_companies,
    user_can_access_company,
)
from notifications.models import Notification
from notifications.services import delete_notifications_for_objects, mark_notifications_read

from .models import CashAdvanceRequest


def _profile(user):
    return getattr(user, 'stafforyx_profile', None)


def user_can_manage_ca(user):
    """HR/admin who may view the CA queue and approve/reject/cancel.

    Mirrors the existing module-permission system: superusers and the
    ``super_admin`` role always pass; otherwise the user must be able to
    manage payroll or employees (HR/payroll request handlers).
    """
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    profile = _profile(user)
    if profile is None:
        return False
    if profile.role == 'super_admin':
        return True
    if not profile.is_active_stafforyx:
        return False
    return bool(profile.can_manage_payroll or profile.can_manage_employees)


def user_can_release_ca(user):
    """Releasing money is restricted to payroll/admin authority."""
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    profile = _profile(user)
    if profile is None:
        return False
    if profile.role == 'super_admin':
        return True
    if not profile.is_active_stafforyx:
        return False
    return bool(profile.can_manage_payroll)


def _require_ca_manager(request):
    if not user_can_manage_ca(request.user):
        raise PermissionDenied


def _selected_ids(request):
    return [
        int(value)
        for value in request.POST.getlist('selected_ids')
        if str(value).isdigit()
    ]


def _history_redirect():
    return redirect(f"{reverse('cash_advance:manage_ca')}?tab=history")


# ── HR/Admin: manage cash-advance requests ────────────────────────────────────

# Ordered tabs shown on the management page. Each maps to a queryset filter.
CA = CashAdvanceRequest
TAB_DEFS = [
    ('pending', 'Pending', {'status': CA.STATUS_PENDING}),
    ('approved', 'Approved', {'status': CA.STATUS_APPROVED}),
    ('released', 'Released', {'status': CA.STATUS_RELEASED,
                              'deduction_status': CA.DEDUCTION_RELEASED}),
    ('scheduled', 'Scheduled for Deduction', {'status': CA.STATUS_RELEASED,
                                              'deduction_status': CA.DEDUCTION_SCHEDULED}),
    ('partial', 'Partially Deducted', {'status': CA.STATUS_RELEASED,
                                       'deduction_status': CA.DEDUCTION_PARTIAL}),
    ('deducted', 'Deducted / Paid Off', {'status': CA.STATUS_RELEASED,
                                         'deduction_status': CA.DEDUCTION_DEDUCTED}),
    ('closed', 'Rejected / Cancelled', {'status__in': [CA.STATUS_REJECTED, CA.STATUS_CANCELLED]}),
    ('history', 'History', None),
]
TAB_FILTERS = {key: flt for key, _label, flt in TAB_DEFS}


@login_required
def manage_ca(request):
    _require_ca_manager(request)

    tab = request.GET.get('tab', 'pending')
    if tab not in TAB_FILTERS:
        tab = 'pending'

    requests = filter_queryset_by_user_companies(
        CashAdvanceRequest.objects.select_related('employee', 'company'),
        request.user,
    )

    if request.method == 'POST':
        if request.POST.get('action') != 'delete_selected':
            messages.error(request, 'Unknown action.')
            return redirect('cash_advance:manage_ca')
        if tab != 'history':
            messages.warning(request, 'Cash advance records can only be deleted from History.')
            return redirect(f"{reverse('cash_advance:manage_ca')}?tab={tab}")

        selected_ids = _selected_ids(request)
        delete_queryset = requests.filter(pk__in=selected_ids)
        delete_ids = list(delete_queryset.values_list('pk', flat=True))
        if delete_ids:
            delete_notifications_for_objects(CashAdvanceRequest, delete_ids)
            deleted_count, _details = delete_queryset.delete()
            messages.success(request, f'Deleted {deleted_count} cash advance record(s).')
        else:
            messages.info(request, 'No cash advance records were selected for deletion.')
        return _history_redirect()

    flt = TAB_FILTERS[tab]
    if flt is not None:
        requests = requests.filter(**flt)

    mark_notifications_read(request.user, notification_type=Notification.TYPE_CASH_ADVANCE_REQUEST)
    return render(request, 'cash_advance/manage_ca.html', {
        'requests': requests,
        'tab': tab,
        'tabs': [(key, label) for key, label, _flt in TAB_DEFS],
        'can_release': user_can_release_ca(request.user),
    })


@login_required
def manage_ca_detail(request, pk):
    _require_ca_manager(request)

    ca = get_object_or_404(
        CashAdvanceRequest.objects.select_related('employee', 'company'), pk=pk
    )
    if not user_can_access_company(request.user, ca.company):
        raise PermissionDenied
    mark_notifications_read(request.user, content_object=ca)

    can_release = user_can_release_ca(request.user)

    if request.method == 'POST':
        action = request.POST.get('action')

        # ── Deduction controls (payroll authority, draft payroll only) ────────
        if action in ('revoke_deduction', 'adjust_deduction'):
            return _handle_deduction_action(request, ca, action, can_release)

        note = request.POST.get('manager_note', ca.manager_note)
        ca.manager_note = note
        now = timezone.now()

        if action == 'approve':
            if ca.status != CashAdvanceRequest.STATUS_PENDING:
                messages.warning(request, 'Only pending requests can be approved.')
                return redirect('cash_advance:manage_ca_detail', pk=ca.pk)
            ca.status = CashAdvanceRequest.STATUS_APPROVED
            ca.approved_by = request.user
            ca.approved_at = now
            ca.save()
            messages.success(request, 'Cash advance request approved.')

        elif action == 'reject':
            if ca.status not in (
                CashAdvanceRequest.STATUS_PENDING, CashAdvanceRequest.STATUS_APPROVED
            ):
                messages.warning(request, 'This request can no longer be rejected.')
                return redirect('cash_advance:manage_ca_detail', pk=ca.pk)
            ca.status = CashAdvanceRequest.STATUS_REJECTED
            ca.rejected_by = request.user
            ca.rejected_at = now
            ca.save()
            messages.success(request, 'Cash advance request rejected.')

        elif action == 'cancel':
            if ca.status in (
                CashAdvanceRequest.STATUS_RELEASED, CashAdvanceRequest.STATUS_CANCELLED
            ):
                messages.warning(request, 'This request can no longer be cancelled.')
                return redirect('cash_advance:manage_ca_detail', pk=ca.pk)
            ca.status = CashAdvanceRequest.STATUS_CANCELLED
            ca.cancel_reason = request.POST.get('cancel_reason', ca.cancel_reason)
            ca.save()
            messages.success(request, 'Cash advance request cancelled.')

        elif action == 'release':
            if not can_release:
                raise PermissionDenied
            if ca.status != CashAdvanceRequest.STATUS_APPROVED:
                messages.warning(request, 'Only approved requests can be released.')
                return redirect('cash_advance:manage_ca_detail', pk=ca.pk)
            ca.status = CashAdvanceRequest.STATUS_RELEASED
            ca.released_by = request.user
            ca.released_at = now
            ca.release_note = request.POST.get('release_note', ca.release_note)
            ca.save()
            messages.success(request, 'Cash advance marked as released.')

        else:
            messages.error(request, 'Unknown action.')
            return redirect('cash_advance:manage_ca_detail', pk=ca.pk)

        return redirect('cash_advance:manage_ca')

    deduction_lines = (
        ca.deduction_adjustments
        .select_related('payroll_record', 'payroll_record__payroll_period')
        .order_by('payroll_record__payroll_period__start_date')
    )
    return render(request, 'cash_advance/manage_ca_detail.html', {
        'ca': ca,
        'can_release': can_release,
        'deduction_lines': deduction_lines,
    })


def _handle_deduction_action(request, ca, action, can_release):
    """Defer/revoke or adjust a CA deduction line on a *draft* payroll record.

    Restricted to payroll-authorized users. Finalized (approved/paid) payroll is
    never modified here.
    """
    from payroll.models import PayrollAdjustment

    if not can_release:
        raise PermissionDenied

    adj = get_object_or_404(
        PayrollAdjustment.objects.select_related('payroll_record'),
        pk=request.POST.get('adjustment_id'),
        source_cash_advance=ca,
    )
    if adj.payroll_record.status != 'draft':
        messages.warning(
            request,
            'This deduction is on a finalized payroll and can no longer be changed.',
        )
        return redirect('cash_advance:manage_ca_detail', pk=ca.pk)

    if action == 'revoke_deduction':
        adj.delete()  # triggers record recalculation + CA reconcile
        messages.success(request, 'Cash advance deduction deferred for this payroll.')
    elif action == 'adjust_deduction':
        from decimal import Decimal, InvalidOperation
        raw = (request.POST.get('amount') or '').strip()
        try:
            new_amount = Decimal(raw)
        except (InvalidOperation, ValueError):
            messages.error(request, 'Invalid deduction amount.')
            return redirect('cash_advance:manage_ca_detail', pk=ca.pk)
        if new_amount <= 0:
            adj.delete()
            messages.success(request, 'Cash advance deduction removed for this payroll.')
        else:
            adj.amount = new_amount
            adj.save()  # triggers record recalculation + CA reconcile
            messages.success(request, 'Cash advance deduction amount updated.')

    return redirect('cash_advance:manage_ca_detail', pk=ca.pk)
