from django import forms

from .models import CompanyHolidayPolicy, Holiday, HolidayException


class HolidayForm(forms.ModelForm):
    class Meta:
        model = Holiday
        fields = ["name", "date", "holiday_type", "is_enabled", "is_paid",
                  "no_work_pay_pct", "worked_multiplier", "notes"]
        widgets = {"date": forms.DateInput(attrs={"type": "date"})}


class HolidayExceptionForm(forms.ModelForm):
    class Meta:
        model = HolidayException
        fields = ["department", "employee", "not_observed",
                  "is_paid_override", "no_work_pay_pct_override",
                  "worked_multiplier_override"]

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        if company is not None:
            self.fields["department"].queryset = company.departments.all()
            self.fields["employee"].queryset = company.employees.all()


class CompanyHolidayPolicyForm(forms.ModelForm):
    class Meta:
        model = CompanyHolidayPolicy
        exclude = ["company", "created_at", "updated_at"]
