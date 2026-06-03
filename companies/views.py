from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render

from accounts.company_access import get_accessible_companies, user_can_access_company

from .forms import CompanyPayslipSettingsForm
from .models import Company


@login_required
def company_payslip_settings(request, pk):
    company = get_object_or_404(Company, pk=pk)
    if not user_can_access_company(request.user, company):
        raise PermissionDenied

    form = CompanyPayslipSettingsForm(
        request.POST or None, request.FILES or None, instance=company
    )
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, f'Payslip settings for "{company.name}" updated.')
        return redirect('companies:payslip_settings', pk=pk)

    return render(request, 'companies/payslip_settings.html', {
        'form': form,
        'company': company,
        'accessible_companies': get_accessible_companies(request.user).order_by('name'),
    })
