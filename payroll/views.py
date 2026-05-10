from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from companies.models import Company
from employees.models import Employee

from .forms import PayrollPeriodForm, PayrollRecordForm
from .models import PayrollPeriod, PayrollRecord


def _employee_salary_map():
    return {
        str(employee.pk): str(employee.basic_salary)
        for employee in Employee.objects.only('id', 'basic_salary')
    }


def payroll_record_list(request):
    records = PayrollRecord.objects.select_related(
        'company', 'payroll_period', 'employee', 'employee__department'
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

    context = {
        'records': records,
        'payroll_periods': PayrollPeriod.objects.select_related('company'),
        'employees': Employee.objects.all().order_by('last_name', 'first_name'),
        'companies': Company.objects.all(),
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
        PayrollRecord.objects.select_related('company', 'payroll_period', 'employee'),
        pk=pk,
    )
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
    })


def payroll_record_delete(request, pk):
    record = get_object_or_404(
        PayrollRecord.objects.select_related('employee', 'payroll_period'),
        pk=pk,
    )
    if request.method == 'POST':
        employee_name = record.employee.full_name
        period_name = record.payroll_period.name
        record.delete()
        messages.success(request, f'Payroll record for {employee_name} in {period_name} has been deleted.')
        return redirect('payroll:payroll_record_list')
    return render(request, 'payroll/payroll_record_confirm_delete.html', {'record': record})


def payroll_period_list(request):
    periods = PayrollPeriod.objects.select_related('company')

    company_id = request.GET.get('company', '')
    if company_id:
        periods = periods.filter(company_id=company_id)

    status = request.GET.get('status', '')
    if status:
        periods = periods.filter(status=status)

    context = {
        'periods': periods,
        'companies': Company.objects.all(),
        'company_filter': company_id,
        'status_filter': status,
        'status_choices': PayrollPeriod.STATUS_CHOICES,
    }
    return render(request, 'payroll/payroll_period_list.html', context)


def payroll_period_add(request):
    form = PayrollPeriodForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        period = form.save()
        messages.success(request, f'Payroll period "{period.name}" created.')
        return redirect('payroll:payroll_period_list')
    return render(request, 'payroll/payroll_period_form.html', {
        'form': form,
        'action': 'Add',
    })


def payroll_period_edit(request, pk):
    period = get_object_or_404(PayrollPeriod, pk=pk)
    form = PayrollPeriodForm(request.POST or None, instance=period)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Payroll period updated successfully.')
        return redirect('payroll:payroll_period_list')
    return render(request, 'payroll/payroll_period_form.html', {
        'form': form,
        'period': period,
        'action': 'Edit',
    })


def payroll_period_delete(request, pk):
    period = get_object_or_404(PayrollPeriod, pk=pk)
    if request.method == 'POST':
        name = period.name
        period.delete()
        messages.success(request, f'Payroll period "{name}" has been deleted.')
        return redirect('payroll:payroll_period_list')
    return render(request, 'payroll/payroll_period_confirm_delete.html', {'period': period})
