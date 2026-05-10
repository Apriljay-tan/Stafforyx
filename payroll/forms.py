from decimal import Decimal

from django import forms

from .models import PayrollPeriod, PayrollRecord


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
        fields = ['company', 'name', 'start_date', 'end_date', 'status']
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrap(self)

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')

        if start_date and end_date and end_date < start_date:
            raise forms.ValidationError('End date must not be earlier than start date.')

        return cleaned_data


class PayrollRecordForm(forms.ModelForm):
    class Meta:
        model = PayrollRecord
        fields = [
            'company', 'payroll_period', 'employee', 'basic_pay',
            'allowances', 'overtime_pay', 'sss_deduction',
            'philhealth_deduction', 'pagibig_deduction', 'tax_deduction',
            'late_deduction', 'absence_deduction', 'other_deductions',
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

        sss_deduction = record.sss_deduction or zero
        philhealth_deduction = record.philhealth_deduction or zero
        pagibig_deduction = record.pagibig_deduction or zero
        tax_deduction = record.tax_deduction or zero
        late_deduction = record.late_deduction or zero
        absence_deduction = record.absence_deduction or zero
        other_deductions = record.other_deductions or zero

        record.gross_pay = basic_pay + allowances + overtime_pay
        total_deductions = (
            sss_deduction + philhealth_deduction + pagibig_deduction +
            tax_deduction + late_deduction + absence_deduction + other_deductions
        )
        record.net_pay = record.gross_pay - total_deductions

        if commit:
            record.save()
            self.save_m2m()

        return record
