from decimal import Decimal

from django import forms

from companies.models import Company

from .models import PayrollAdjustment, PayrollPeriod, PayrollRecord


def _bootstrap(form):
    for field in form.fields.values():
        widget = field.widget
        if isinstance(widget, forms.CheckboxInput):
            widget.attrs.setdefault('class', 'form-check-input')
        elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
            widget.attrs.setdefault('class', 'form-select')
        else:
            widget.attrs.setdefault('class', 'form-control')


class PayrollPeriodForm(forms.ModelForm):
    class Meta:
        model = PayrollPeriod
        fields = ['company', 'name', 'start_date', 'end_date', 'pay_date', 'cutoff_type', 'status']
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date':   forms.DateInput(attrs={'type': 'date'}),
            'pay_date':   forms.DateInput(attrs={'type': 'date'}),
        }
        labels = {
            'start_date': 'Cutoff Start Date',
            'end_date':   'Cutoff End Date',
            'pay_date':   'Pay Date',
            'cutoff_type': 'Cutoff Type',
        }
        help_texts = {
            'start_date': 'Use any cutoff range, for example 1–15, 16–30, 5–20, or 21–4.',
            'end_date':   'Must be the same date or later than the cutoff start.',
            'pay_date':   'The date employees will be paid. Can be after the cutoff end date.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['pay_date'].required = False
        _bootstrap(self)

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')
        if start_date and end_date and end_date < start_date:
            self.add_error('end_date', 'Cutoff end date must not be earlier than start date.')
        return cleaned_data


class PayrollRecordForm(forms.ModelForm):
    class Meta:
        model = PayrollRecord
        fields = [
            'company', 'payroll_period', 'employee',
            'basic_pay', 'allowances', 'overtime_pay',
            'sss_deduction', 'philhealth_deduction', 'pagibig_deduction',
            'tax_deduction', 'late_deduction', 'undertime_deduction',
            'absence_deduction', 'other_deductions',
            'status',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrap(self)

    def save(self, commit=True):
        record = super().save(commit=False)

        # Default basic_pay from employee salary when the field is left blank.
        if not record.basic_pay and record.employee_id:
            record.basic_pay = Decimal(str(record.employee.basic_salary or 0))

        if commit:
            record.save()
            self.save_m2m()
            # recalculate() is the single source of truth for gross_pay / net_pay.
            # It includes holiday_pay and all PayrollAdjustment entries so that
            # manually-added deductions/earnings survive a form save.
            record.recalculate()

        return record


class PayrollAdjustmentForm(forms.ModelForm):
    class Meta:
        model = PayrollAdjustment
        fields = ['name', 'adjustment_type', 'amount', 'remarks']
        widgets = {
            'remarks': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrap(self)


class ArchiveFilterForm(forms.Form):
    """Select a company + a payroll period and/or an explicit date range."""
    company = forms.ModelChoiceField(
        queryset=Company.objects.none(),
        empty_label='Select company…',
    )
    payroll_period = forms.ModelChoiceField(
        queryset=PayrollPeriod.objects.none(),
        required=False,
        empty_label='Use date range below…',
        help_text='Optional. If chosen, its cutoff dates define the range.',
    )
    date_from = forms.DateField(
        required=False, widget=forms.DateInput(attrs={'type': 'date'}),
    )
    date_to = forms.DateField(
        required=False, widget=forms.DateInput(attrs={'type': 'date'}),
    )

    def __init__(self, *args, accessible_companies=None, **kwargs):
        super().__init__(*args, **kwargs)
        if accessible_companies is not None:
            self.fields['company'].queryset = accessible_companies.order_by('name')
            self.fields['payroll_period'].queryset = (
                PayrollPeriod.objects.filter(company__in=accessible_companies)
                .select_related('company').order_by('-start_date')
            )
        _bootstrap(self)

    def clean(self):
        cleaned = super().clean()
        period = cleaned.get('payroll_period')
        date_from = cleaned.get('date_from')
        date_to = cleaned.get('date_to')

        if period is not None:
            # A selected period fully defines the range.
            cleaned['date_from'] = period.start_date
            cleaned['date_to'] = period.end_date
            if period.company_id != getattr(cleaned.get('company'), 'pk', None):
                self.add_error('payroll_period', 'Period does not belong to the selected company.')
            return cleaned

        if not date_from or not date_to:
            raise forms.ValidationError(
                'Choose a payroll period, or provide both a date-from and date-to.'
            )
        if date_to < date_from:
            self.add_error('date_to', 'Date-to must not be earlier than date-from.')
        return cleaned
