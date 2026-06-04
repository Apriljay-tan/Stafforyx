from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.company_access import (
    filter_queryset_by_user_companies,
    user_can_access_company,
)

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


# ── HR/Admin: manage cash-advance requests ────────────────────────────────────

# Tab key → statuses included in that tab.
TAB_FILTERS = {
    'pending': [CashAdvanceRequest.STATUS_PENDING],
    'approved': [CashAdvanceRequest.STATUS_APPROVED],
    'released': [CashAdvanceRequest.STATUS_RELEASED],
    'closed': [CashAdvanceRequest.STATUS_REJECTED, CashAdvanceRequest.STATUS_CANCELLED],
    'history': None,  # everything
}


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

    statuses = TAB_FILTERS[tab]
    if statuses is not None:
        requests = requests.filter(status__in=statuses)

    return render(request, 'cash_advance/manage_ca.html', {
        'requests': requests,
        'tab': tab,
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

    can_release = user_can_release_ca(request.user)

    if request.method == 'POST':
        action = request.POST.get('action')
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

    return render(request, 'cash_advance/manage_ca_detail.html', {
        'ca': ca,
        'can_release': can_release,
    })
