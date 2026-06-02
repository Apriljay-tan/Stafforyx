from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.access import module_access_required
from accounts.company_access import get_selected_company_from_request, user_can_access_company

from .forms import CompanyHolidayPolicyForm, HolidayExceptionForm, HolidayForm
from .models import Holiday, HolidayException
from .seeding import get_or_create_policy

holiday_access = module_access_required("can_manage_payroll")


def _require_company(request):
    company = get_selected_company_from_request(request)
    if company is None:
        return None
    return company


def _get_company_holiday(request, pk):
    holiday = get_object_or_404(Holiday, pk=pk)
    if not user_can_access_company(request.user, holiday.company):
        raise PermissionDenied
    return holiday


@holiday_access
def holiday_list(request):
    company = _require_company(request)
    if company is None:
        messages.info(request, "Select a company to manage holidays.")
        return redirect("/")
    holidays = Holiday.objects.filter(company=company)
    type_filter = request.GET.get("type", "")
    if type_filter:
        holidays = holidays.filter(holiday_type=type_filter)
    return render(request, "holidays/holiday_list.html", {
        "holidays": holidays, "company": company, "type_filter": type_filter,
    })


@holiday_access
@require_POST
def holiday_toggle(request, pk):
    holiday = _get_company_holiday(request, pk)
    holiday.is_enabled = not holiday.is_enabled
    holiday.save(update_fields=["is_enabled"])
    messages.success(request, f'"{holiday.name}" {"enabled" if holiday.is_enabled else "disabled"}.')
    return redirect("holidays:holiday_list")


@holiday_access
def holiday_add(request):
    company = _require_company(request)
    if company is None:
        return redirect("/")
    form = HolidayForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        holiday = form.save(commit=False)
        holiday.company = company
        holiday.source = "company"
        holiday.save()
        messages.success(request, f'Holiday "{holiday.name}" added.')
        return redirect("holidays:holiday_list")
    return render(request, "holidays/holiday_form.html", {"form": form, "action": "Add"})


@holiday_access
def holiday_edit(request, pk):
    holiday = _get_company_holiday(request, pk)
    form = HolidayForm(request.POST or None, instance=holiday)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f'Holiday "{holiday.name}" updated.')
        return redirect("holidays:holiday_list")
    return render(request, "holidays/holiday_form.html", {"form": form, "action": "Edit"})


@holiday_access
def holiday_delete(request, pk):
    holiday = _get_company_holiday(request, pk)
    if request.method == "POST":
        holiday.delete()
        messages.success(request, "Holiday deleted.")
        return redirect("holidays:holiday_list")
    return render(request, "holidays/holiday_detail.html", {"holiday": holiday, "confirm_delete": True})


@holiday_access
def holiday_detail(request, pk):
    holiday = _get_company_holiday(request, pk)
    return render(request, "holidays/holiday_detail.html", {
        "holiday": holiday, "exceptions": holiday.exceptions.all(),
    })


@holiday_access
def exception_add(request, pk):
    holiday = _get_company_holiday(request, pk)
    form = HolidayExceptionForm(request.POST or None, company=holiday.company)
    if request.method == "POST" and form.is_valid():
        exc = form.save(commit=False)
        exc.holiday = holiday
        exc.full_clean()  # enforces exactly-one-target
        exc.save()
        messages.success(request, "Exception added.")
        return redirect("holidays:holiday_detail", pk=holiday.pk)
    return render(request, "holidays/exception_form.html", {"form": form, "holiday": holiday})


@holiday_access
@require_POST
def exception_delete(request, pk):
    exc = get_object_or_404(HolidayException, pk=pk)
    if not user_can_access_company(request.user, exc.holiday.company):
        raise PermissionDenied
    holiday_pk = exc.holiday_id
    exc.delete()
    messages.success(request, "Exception removed.")
    return redirect("holidays:holiday_detail", pk=holiday_pk)


@holiday_access
def policy_edit(request):
    company = _require_company(request)
    if company is None:
        return redirect("/")
    policy = get_or_create_policy(company)
    form = CompanyHolidayPolicyForm(request.POST or None, instance=policy)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Holiday policy updated.")
        return redirect("holidays:holiday_list")
    return render(request, "holidays/policy_form.html", {"form": form, "company": company})
