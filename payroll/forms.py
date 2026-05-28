from decimal import Decimal

from django import forms

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
        zero = Decimal('0.00')

        basic_pay = record.basic_pay or zero
        if basic_pay == zero and record.employee_id:
            basic_pay = record.employee.basic_salary or zero
            record.basic_pay = basic_pay

        allowances = record.allowances or zero
        overtime_pay = record.overtime_pay or zero
        sss = record.sss_deduction or zero
        philhealth = record.philhealth_deduction or zero
        pagibig = record.pagibig_deduction or zero
        tax = record.tax_deduction or zero
        late = record.late_deduction or zero
        undertime = record.undertime_deduction or zero
        other = record.other_deductions or zero

        record.gross_pay = basic_pay + allowances + overtime_pay
        record.net_pay = record.gross_pay - (sss + philhealth + pagibig + tax + late + undertime + other)

        if commit:
            record.save()
            self.save_m2m()

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
