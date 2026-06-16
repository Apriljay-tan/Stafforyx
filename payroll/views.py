from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from accounts.company_access import filter_queryset_by_user_companies, user_can_access_company
from companies.models import Company
from employees.models import Department, Employee

from .forms import PayrollAdjustmentForm, PayrollPeriodForm, PayrollRecordForm
from .models import PayrollAdjustment, PayrollPeriod, PayrollRecord


def _attach_payroll_display(record):
    totals = record.calculate_totals()
    record.display_gross_pay = totals['gross_pay']
    record.display_total_deductions = totals['total_deductions']
    record.display_net_pay = totals['net_pay']
    record.show_daily_rate = bool(record.basic_pay or record.payable_days)
    record.show_hourly_rate = bool(
        record.overtime_pay or record.overtime_minutes or
        record.night_differential_pay or record.night_differential_minutes or
        record.late_deduction or record.late_minutes or
        record.undertime_deduction or record.undertime_minutes
    )
    record.show_regular_ot_rate = bool(record.overtime_pay or record.overtime_minutes)
    record.show_night_diff_rate = bool(
        record.night_differential_pay or record.night_differential_minutes
    )
    # Payroll currently stores holiday pay, but not separate rest-day or holiday
    # overtime pay components. Avoid displaying OT rates that are not represented
    # by actual payslip rows.
    record.show_rest_day_ot_rate = False
    record.show_holiday_ot_rate = False
    record.show_rate_information = any((
        record.show_daily_rate,
        record.show_hourly_rate,
        record.show_regular_ot_rate,
        record.show_night_diff_rate,
        record.show_rest_day_ot_rate,
        record.show_holiday_ot_rate,
    ))
    return record


def _employee_salary_map():
    return {
        str(emp.pk): str(emp.basic_salary)
        for emp in Employee.objects.only('id', 'basic_salary')
    }


# ── Payroll Records ────────────────────────────────────────────────────────────

def payroll_record_list(request):
    records = filter_queryset_by_user_companies(
        PayrollRecord.objects.select_related(
            'company', 'payroll_period', 'employee', 'employee__department'
        ).prefetch_related('adjustments'),
        request.user,
    )

    payroll_period_id = request.GET.get('payroll_period', '')
    if payroll_period_id:
        records = records.filter(payroll_period_id=payroll_period_id)

    employee_id = request.GET.get('employee', '')
    if employee_id:
        records = records.filter(employee_id=employee_id)

    status = request.GET.get('status', '')
    if status:
        records = records.filter(status=status)

    company_id = request.GET.get('company', '')
    if company_id:
        records = records.filter(company_id=company_id)

    for record in records:
        _attach_payroll_display(record)

    accessible_companies = filter_queryset_by_user_companies(Company.objects.all(), request.user)
    context = {
        'records': records,
        'payroll_periods': filter_queryset_by_user_companies(
            PayrollPeriod.objects.all(), request.user
        ).select_related('company'),
        'employees': filter_queryset_by_user_companies(
            Employee.objects.all(), request.user
        ).order_by('last_name', 'first_name'),
        'companies': accessible_companies,
        'payroll_period_filter': payroll_period_id,
        'employee_filter': employee_id,
        'status_filter': status,
        'company_filter': company_id,
        'status_choices': PayrollRecord.STATUS_CHOICES,
    }
    return render(request, 'payroll/payroll_record_list.html', context)


def payroll_record_add(request):
    form = PayrollRecordForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Payroll record added successfully.')
        return redirect('payroll:payroll_record_list')
    return render(request, 'payroll/payroll_record_form.html', {
        'form': form,
        'action': 'Add',
        'employee_salary_map': _employee_salary_map(),
    })


def payroll_record_edit(request, pk):
    record = get_object_or_404(
        PayrollRecord.objects.select_related(
            'company', 'payroll_period', 'employee'
        ).prefetch_related('adjustments'),
        pk=pk,
    )
    if not user_can_access_company(request.user, record.company):
        raise PermissionDenied
    _attach_payroll_display(record)
    form = PayrollRecordForm(request.POST or None, instance=record)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Payroll record updated successfully.')
        return redirect('payroll:payroll_record_list')
    return render(request, 'payroll/payroll_record_form.html', {
        'form': form,
        'record': record,
        'action': 'Edit',
        'employee_salary_map': _employee_salary_map(),
        'adjustments': record.adjustments.all(),
        'adjustment_form': PayrollAdjustmentForm(),
    })


def payroll_record_delete(request, pk):
    record = get_object_or_404(
        PayrollRecord.objects.select_related('employee', 'payroll_period', 'company'),
        pk=pk,
    )
    if not user_can_access_company(request.user, record.company):
        raise PermissionDenied
    if request.method == 'POST':
        employee_name = record.employee.full_name
        period_name = record.payroll_period.name
        record.delete()
        messages.success(request, f'Payroll record for {employee_name} in {period_name} deleted.')
        return redirect('payroll:payroll_record_list')
    return render(request, 'payroll/payroll_record_confirm_delete.html', {'record': record})


# ── Approval workflow ──────────────────────────────────────────────────────────

def _safe_payroll_redirect(request):
    """Return a redirect back to the originating list view, preserving filters."""
    next_url = request.POST.get('next', '')
    if next_url and url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return redirect(next_url)
    return redirect('payroll:payroll_record_list')


@require_POST
def payroll_record_approve(request, pk):
    record = get_object_or_404(
        PayrollRecord.objects.select_related('company', 'employee', 'payroll_period'),
        pk=pk,
    )
    if not user_can_access_company(request.user, record.company):
        raise PermissionDenied

    if record.status == 'draft':
        record.status = 'approved'
        # Only the status field is written — payroll snapshot values are preserved.
        record.save(update_fields=['status'])
        messages.success(request, 'Payroll record approved.')
    else:
        messages.warning(
            request,
            f'Only draft payroll records can be approved — '
            f'this record is already {record.get_status_display()}.',
        )
    return _safe_payroll_redirect(request)


@require_POST
def payroll_record_bulk_action(request):
    bulk_action = (request.POST.get('bulk_action') or '').strip()
    selected_ids = request.POST.getlist('selected_records')

    if bulk_action not in ('approve', 'delete'):
        messages.error(request, 'Unknown bulk action requested.')
        return _safe_payroll_redirect(request)

    if not selected_ids:
        messages.warning(request, 'No payroll records were selected.')
        return _safe_payroll_redirect(request)

    # Company scoping: only records the user may access are ever touched.
    scoped = filter_queryset_by_user_companies(
        PayrollRecord.objects.all(), request.user
    ).filter(pk__in=selected_ids)
    total_selected = scoped.count()

    if bulk_action == 'approve':
        # .update() bypasses save(), so payroll snapshot values are preserved.
        approved_count = scoped.filter(status='draft').update(status='approved')
        skipped = total_selected - approved_count
        if approved_count:
            msg = f'{approved_count} payroll record(s) approved.'
            if skipped:
                msg += f' {skipped} skipped (not draft).'
            messages.success(request, msg)
        else:
            messages.warning(
                request, 'No payroll records approved — selected records are not draft.'
            )
        return _safe_payroll_redirect(request)

    # bulk_action == 'delete' — only draft records may be deleted.
    deletable = scoped.filter(status__in=PayrollRecord.DELETABLE_STATUSES)
    deletable_count = deletable.count()
    skipped = total_selected - deletable_count
    if deletable_count:
        deletable.delete()
        msg = f'{deletable_count} draft payroll record(s) deleted.'
        if skipped:
            msg += f' {skipped} skipped because they were already approved or paid.'
        messages.success(request, msg)
    else:
        messages.warning(
            request,
            'No payroll records deleted — approved/paid records cannot be deleted.',
        )
    return _safe_payroll_redirect(request)


# ── Generate Payroll ───────────────────────────────────────────────────────────

def payroll_generate(request):
    periods = (
        filter_queryset_by_user_companies(PayrollPeriod.objects.all(), request.user)
        .select_related('company')
        .order_by('-start_date')
    )
    departments = (
        filter_queryset_by_user_companies(Department.objects.all(), request.user)
        .select_related('company')
        .order_by('company__name', 'name')
    )

    if request.method == 'POST':
        period_id = request.POST.get('payroll_period', '').strip()
        department_id = request.POST.get('department', '').strip() or None
        allow_update = request.POST.get('allow_update_draft') == '1'

        if not period_id:
            messages.error(request, 'Please select a payroll period.')
            return render(request, 'payroll/payroll_generate.html', {
                'periods': periods, 'departments': departments,
            })

        period = get_object_or_404(PayrollPeriod.objects.select_related('company'), pk=period_id)
        if not user_can_access_company(request.user, period.company):
            raise PermissionDenied

        from .services import generate_payroll_for_period
        created, updated, skipped = generate_payroll_for_period(
            period, department_id=department_id, allow_update_draft=allow_update,
        )

        parts = []
        if created:
            parts.append(f'{created} record(s) created')
        if updated:
            parts.append(f'{updated} draft(s) recalculated')
        if skipped:
            parts.append(f'{skipped} approved/paid record(s) skipped')

        if created or updated:
            messages.success(request, f'"{period.name}": ' + ', '.join(parts) + '.')
        elif skipped:
            messages.warning(request, f'No changes — all records for "{period.name}" are approved/paid.')
        else:
            messages.warning(request, f'No active employees found for the selected filters.')

        return redirect(reverse('payroll:payroll_record_list') + f'?payroll_period={period.pk}')

    return render(request, 'payroll/payroll_generate.html', {
        'periods': periods,
        'departments': departments,
    })


# ── Payroll Periods ────────────────────────────────────────────────────────────

def payroll_period_list(request):
    periods = filter_queryset_by_user_companies(
        PayrollPeriod.objects.select_related('company'), request.user
    )

    company_id = request.GET.get('company', '')
    if company_id:
        periods = periods.filter(company_id=company_id)

    status = request.GET.get('status', '')
    if status:
        periods = periods.filter(status=status)

    accessible_companies = filter_queryset_by_user_companies(Company.objects.all(), request.user)
    return render(request, 'payroll/payroll_period_list.html', {
        'periods': periods,
        'companies': accessible_companies,
        'company_filter': company_id,
        'status_filter': status,
        'status_choices': PayrollPeriod.STATUS_CHOICES,
    })


def payroll_period_add(request):
    form = PayrollPeriodForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        period = form.save()
        messages.success(request, f'Payroll period "{period.name}" created.')
        return redirect('payroll:payroll_period_list')
    return render(request, 'payroll/payroll_period_form.html', {'form': form, 'action': 'Add'})


def payroll_period_edit(request, pk):
    period = get_object_or_404(PayrollPeriod.objects.select_related('company'), pk=pk)
    if not user_can_access_company(request.user, period.company):
        raise PermissionDenied
    form = PayrollPeriodForm(request.POST or None, instance=period)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Payroll period updated successfully.')
        return redirect('payroll:payroll_period_list')
    return render(request, 'payroll/payroll_period_form.html', {'form': form, 'period': period, 'action': 'Edit'})


def payroll_period_delete(request, pk):
    period = get_object_or_404(PayrollPeriod.objects.select_related('company'), pk=pk)
    if not user_can_access_company(request.user, period.company):
        raise PermissionDenied
    if request.method == 'POST':
        name = period.name
        period.delete()
        messages.success(request, f'Payroll period "{name}" deleted.')
        return redirect('payroll:payroll_period_list')
    return render(request, 'payroll/payroll_period_confirm_delete.html', {'period': period})


# ── Payslip ────────────────────────────────────────────────────────────────────

def payslip_view(request, pk):
    from decimal import Decimal
    record = get_object_or_404(
        PayrollRecord.objects.select_related(
            'company', 'payroll_period', 'employee',
            'employee__department', 'employee__position',
        ).prefetch_related('adjustments'),
        pk=pk,
    )
    if not user_can_access_company(request.user, record.company):
        raise PermissionDenied

    earning_adjs = record.adjustments.filter(adjustment_type='earning')
    deduction_adjs = record.adjustments.filter(adjustment_type='deduction')

    hourly_rate = record.hourly_rate or Decimal('0')
    q2 = Decimal('0.01')
    _attach_payroll_display(record)

    return render(request, 'payroll/payslip.html', {
        'record': record,
        'earning_adjs': earning_adjs,
        'deduction_adjs': deduction_adjs,
        'company': record.company,
        'regular_ot_rate': (
            hourly_rate * Decimal(str(record.overtime_multiplier or '1.25'))
        ).quantize(q2),
        'night_diff_rate': (
            hourly_rate
            * Decimal(str(record.night_differential_percentage or 0))
            / Decimal('100')
        ).quantize(q2),
        'rest_day_ot_rate': (hourly_rate * Decimal('1.30')).quantize(q2),
        'holiday_ot_rate': (hourly_rate * Decimal('2.60')).quantize(q2),
        'gross_pay': record.display_gross_pay,
        'total_deductions': record.display_total_deductions,
        'net_pay': record.display_net_pay,
    })


def payslip_send_email(request, pk):
    record = get_object_or_404(
        PayrollRecord.objects.select_related('company', 'payroll_period', 'employee'),
        pk=pk,
    )
    if not user_can_access_company(request.user, record.company):
        raise PermissionDenied
    if request.method != 'POST':
        return redirect('payroll:payslip_view', pk=pk)

    employee = record.employee
    if not employee.email:
        messages.error(request, f'{employee.full_name} has no email address on file.')
        return redirect('payroll:payslip_view', pk=pk)

    from django.conf import settings as django_settings
    from django.core.mail import EmailMessage
    from django.template.loader import render_to_string

    try:
        html_body = render_to_string('payroll/payslip_email.html', {
            'record': record,
            'company': record.company,
            'earning_adjs': record.adjustments.filter(adjustment_type='earning'),
            'deduction_adjs': record.adjustments.filter(adjustment_type='deduction'),
            'gross_pay': record.calculated_gross_pay,
            'total_deductions': record.calculated_total_deductions,
            'net_pay': record.calculated_net_pay,
        }, request=request)

        from_email = getattr(django_settings, 'DEFAULT_FROM_EMAIL', None) or \
                     getattr(django_settings, 'EMAIL_HOST_USER', None) or \
                     'payroll@stafforyx.app'

        msg = EmailMessage(
            subject=f'Payslip — {record.payroll_period.name} ({record.company.name})',
            body=html_body,
            from_email=from_email,
            to=[employee.email],
        )
        msg.content_subtype = 'html'
        msg.send(fail_silently=False)

        # Stamp sent time
        from django.utils import timezone
        record.payslip_sent_at = timezone.now()
        record.save(update_fields=['payslip_sent_at'])

        messages.success(request, f'Payslip sent to {employee.email}.')

    except Exception as exc:
        messages.error(
            request,
            f'Could not send email: {exc}. '
            'Check your EMAIL_HOST settings in config/settings.py.',
        )

    return redirect('payroll:payslip_view', pk=pk)


# ── PayrollAdjustments ─────────────────────────────────────────────────────────

def adjustment_add(request, record_pk):
    record = get_object_or_404(
        PayrollRecord.objects.select_related('company'),
        pk=record_pk,
    )
    if not user_can_access_company(request.user, record.company):
        raise PermissionDenied

    if request.method == 'POST':
        form = PayrollAdjustmentForm(request.POST)
        if form.is_valid():
            adj = form.save(commit=False)
            adj.payroll_record = record
            adj.save()
            messages.success(request, f'Adjustment "{adj.name}" added.')
        else:
            messages.error(request, 'Invalid adjustment data.')

    return redirect('payroll:payroll_record_edit', pk=record_pk)


def adjustment_delete(request, pk):
    adj = get_object_or_404(
        PayrollAdjustment.objects.select_related('payroll_record__company'),
        pk=pk,
    )
    record = adj.payroll_record
    if not user_can_access_company(request.user, record.company):
        raise PermissionDenied

    if request.method == 'POST':
        name = adj.name
        record_pk = record.pk
        adj.delete()
        messages.success(request, f'Adjustment "{name}" removed.')
        return redirect('payroll:payroll_record_edit', pk=record_pk)

    return render(request, 'payroll/adjustment_confirm_delete.html', {'adj': adj})
