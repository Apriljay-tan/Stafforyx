import datetime

from django import forms
from django.contrib.auth.models import User

from employees.models import Employee
from .models import (
    AttendanceLocation, AttendanceRecord,
    EmployeeDailySchedule, ShiftTemplate, WorkSchedule,
)


def _bootstrap(form):
    for field in form.fields.values():
        widget = field.widget
        if isinstance(widget, forms.CheckboxInput):
            widget.attrs.setdefault('class', 'form-check-input')
        elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
            widget.attrs.setdefault('class', 'form-select')
        else:
            widget.attrs.setdefault('class', 'form-control')


class AttendanceRecordForm(forms.ModelForm):
    class Meta:
        model = AttendanceRecord
        fields = [
            'company', 'employee', 'date', 'time_in', 'time_out',
            'break_minutes', 'total_hours', 'late_minutes',
            'overtime_hours', 'status', 'remarks',
        ]
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'time_in': forms.TimeInput(attrs={'type': 'time'}),
            'time_out': forms.TimeInput(attrs={'type': 'time'}),
            'remarks': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrap(self)


class ShiftTemplateForm(forms.ModelForm):
    class Meta:
        model = ShiftTemplate
        fields = [
            'company', 'name', 'start_time', 'end_time',
            'break_minutes', 'grace_minutes',
            'allow_early_clock_in_minutes', 'overtime_after_minutes',
            'is_overnight', 'is_active', 'notes',
        ]
        widgets = {
            'start_time': forms.TimeInput(attrs={'type': 'time'}),
            'end_time':   forms.TimeInput(attrs={'type': 'time'}),
            'notes':      forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrap(self)


class EmployeeDailyScheduleForm(forms.ModelForm):
    class Meta:
        model = EmployeeDailySchedule
        fields = [
            'company', 'employee', 'schedule_date', 'shift_template',
            'custom_start_time', 'custom_end_time',
            'break_minutes', 'grace_minutes',
            'is_rest_day', 'reason',
        ]
        widgets = {
            'schedule_date':    forms.DateInput(attrs={'type': 'date'}),
            'custom_start_time': forms.TimeInput(attrs={'type': 'time'}),
            'custom_end_time':   forms.TimeInput(attrs={'type': 'time'}),
            'reason':            forms.TextInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrap(self)


class BulkRosterForm(forms.Form):
    """Generate EmployeeDailySchedule rows for a set of employees over a date range."""
    WEEKDAY_CHOICES = [
        (0, 'Monday'), (1, 'Tuesday'), (2, 'Wednesday'),
        (3, 'Thursday'), (4, 'Friday'), (5, 'Saturday'), (6, 'Sunday'),
    ]

    company = forms.ModelChoiceField(
        queryset=None,
        help_text='All employees in the company can be targeted.',
    )
    shift_template = forms.ModelChoiceField(queryset=ShiftTemplate.objects.none())
    date_from = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
    date_to = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
    weekdays = forms.MultipleChoiceField(
        choices=WEEKDAY_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        required=False,
        help_text='Leave all unchecked to generate for every day in the range.',
    )
    overwrite_existing = forms.BooleanField(
        required=False,
        help_text='Replace existing daily schedules in the date range.',
    )

    def __init__(self, *args, accessible_companies=None, **kwargs):
        super().__init__(*args, **kwargs)
        if accessible_companies is not None:
            self.fields['company'].queryset = accessible_companies
            self.fields['shift_template'].queryset = ShiftTemplate.objects.filter(
                company__in=accessible_companies, is_active=True
            )
        _bootstrap(self)
        # Override checkboxes — _bootstrap would set form-check-input, which is correct
        self.fields['weekdays'].widget.attrs.pop('class', None)
        self.fields['overwrite_existing'].widget.attrs.setdefault('class', 'form-check-input')

    def clean(self):
        cleaned = super().clean()
        d_from = cleaned.get('date_from')
        d_to = cleaned.get('date_to')
        if d_from and d_to and d_to < d_from:
            raise forms.ValidationError('Date To must be on or after Date From.')
        company = cleaned.get('company')
        shift = cleaned.get('shift_template')
        if company and shift and shift.company != company:
            raise forms.ValidationError('Shift Template does not belong to the selected company.')
        return cleaned


class AttendanceLocationForm(forms.ModelForm):
    class Meta:
        model = AttendanceLocation
        fields = [
            'company', 'name', 'address',
            'ip_address', 'cidr_range',
            'is_active', 'require_selfie', 'require_gps', 'notes',
        ]
        widgets = {
            'address': forms.Textarea(attrs={'rows': 2}),
            'notes':   forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrap(self)


class WorkScheduleForm(forms.ModelForm):
    class Meta:
        model = WorkSchedule
        fields = [
            'company', 'name',
            'start_time', 'end_time', 'overtime_after',
            'grace_minutes', 'break_minutes', 'required_hours', 'half_day_cutoff_time',
            'use_employee_hourly_rate_for_late', 'late_deduction_rate_per_hour',
            'use_employee_hourly_rate_for_undertime', 'undertime_deduction_rate_per_hour',
            'work_monday', 'work_tuesday', 'work_wednesday', 'work_thursday',
            'work_friday', 'work_saturday', 'work_sunday',
            'is_active',
        ]
        widgets = {
            'start_time':     forms.TimeInput(attrs={'type': 'time'}),
            'end_time':       forms.TimeInput(attrs={'type': 'time'}),
            'overtime_after': forms.TimeInput(attrs={'type': 'time'}),
            'half_day_cutoff_time': forms.TimeInput(attrs={'type': 'time'}),
            'late_deduction_rate_per_hour': forms.NumberInput(attrs={'min': '0', 'step': '0.01'}),
            'undertime_deduction_rate_per_hour': forms.NumberInput(attrs={'min': '0', 'step': '0.01'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrap(self)

    def clean(self):
        cleaned = super().clean()
        use_employee_late = cleaned.get('use_employee_hourly_rate_for_late')
        late_rate = cleaned.get('late_deduction_rate_per_hour')
        use_employee_undertime = cleaned.get('use_employee_hourly_rate_for_undertime')
        undertime_rate = cleaned.get('undertime_deduction_rate_per_hour')

        if not use_employee_late and late_rate is None:
            self.add_error(
                'late_deduction_rate_per_hour',
                'Enter a fixed late deduction amount, or use the employee hourly rate.',
            )
        if not use_employee_undertime and undertime_rate is None:
            self.add_error(
                'undertime_deduction_rate_per_hour',
                'Enter a fixed undertime deduction amount, or use the employee hourly rate.',
            )
        return cleaned
