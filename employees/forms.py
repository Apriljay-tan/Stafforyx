from django import forms
from .models import Employee, Department, Position


def _bootstrap(form):
    for field in form.fields.values():
        w = field.widget
        if isinstance(w, forms.CheckboxInput):
            w.attrs.setdefault('class', 'form-check-input')
        elif isinstance(w, forms.CheckboxSelectMultiple):
            w.attrs.setdefault('class', 'form-check-input')
        elif isinstance(w, (forms.Select, forms.SelectMultiple)):
            w.attrs.setdefault('class', 'form-select')
        else:
            w.attrs.setdefault('class', 'form-control')


class DepartmentForm(forms.ModelForm):
    class Meta:
        model = Department
        fields = ['company', 'name', 'description']
        widgets = {'description': forms.Textarea(attrs={'rows': 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrap(self)


class PositionForm(forms.ModelForm):
    class Meta:
        model = Position
        fields = ['company', 'department', 'title', 'description']
        widgets = {'description': forms.Textarea(attrs={'rows': 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrap(self)


class EmployeeForm(forms.ModelForm):
    flexible_day_offs = forms.MultipleChoiceField(
        choices=Employee.FLEXIBLE_DAY_OFF_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label='Flexible day-offs',
        help_text='Days not normally required for flexible employees unless worked.',
    )

    class Meta:
        model = Employee
        fields = [
            'company', 'employee_id', 'photo',
            'first_name', 'middle_name', 'last_name',
            'email', 'phone', 'address',
            'date_hired', 'department', 'position',
            'employment_type', 'status', 'pay_basis', 'basic_salary', 'daily_rate',
            'work_schedule',
            'attendance_policy_type', 'required_daily_hours', 'default_break_minutes',
            'flexible_overtime_grace_minutes', 'overtime_policy', 'overtime_multiplier',
            'flexible_day_offs',
            'night_differential_enabled',
            'night_differential_percentage', 'night_differential_start_time',
            'night_differential_end_time', 'allow_other_registered_locations',
            'biometric_user_id',
            'sss_number', 'philhealth_number', 'pagibig_number', 'tin_number',
            'sss_contribution_amount', 'philhealth_contribution_amount',
            'pagibig_contribution_amount', 'tax_deduction_amount',
            'emergency_contact_name', 'emergency_contact_phone',
        ]
        widgets = {
            'date_hired': forms.DateInput(attrs={'type': 'date'}),
            'address': forms.Textarea(attrs={'rows': 3}),
            'night_differential_start_time': forms.TimeInput(attrs={'type': 'time'}),
            'night_differential_end_time': forms.TimeInput(attrs={'type': 'time'}),
            'overtime_multiplier': forms.NumberInput(attrs={'min': '1.0', 'max': '5.0', 'step': '0.05'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Lazy import avoids circular dependency (attendance.models → employees.models)
        from attendance.models import WorkSchedule
        self.fields['work_schedule'].queryset = WorkSchedule.objects.filter(is_active=True)
        self.fields['work_schedule'].required = False
        _bootstrap(self)

    def clean_required_daily_hours(self):
        value = self.cleaned_data['required_daily_hours']
        if value <= 0:
            raise forms.ValidationError('Required daily hours must be positive.')
        return value

    def clean_default_break_minutes(self):
        value = self.cleaned_data['default_break_minutes']
        if value < 0:
            raise forms.ValidationError('Break minutes must not be negative.')
        return value

    def clean_flexible_overtime_grace_minutes(self):
        value = self.cleaned_data['flexible_overtime_grace_minutes']
        if value < 0:
            raise forms.ValidationError('Overtime grace minutes must not be negative.')
        return value

    def clean_night_differential_percentage(self):
        value = self.cleaned_data['night_differential_percentage']
        if value < 0:
            raise forms.ValidationError('Night differential percentage must not be negative.')
        return value

    def clean_flexible_day_offs(self):
        return list(self.cleaned_data.get('flexible_day_offs') or [])
