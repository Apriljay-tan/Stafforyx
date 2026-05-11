from django import forms
from .models import Employee, Department, Position


def _bootstrap(form):
    for field in form.fields.values():
        w = field.widget
        if isinstance(w, forms.CheckboxInput):
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
    class Meta:
        model = Employee
        fields = [
            'company', 'employee_id', 'photo',
            'first_name', 'middle_name', 'last_name',
            'email', 'phone', 'address',
            'date_hired', 'department', 'position',
            'employment_type', 'status', 'basic_salary',
            'work_schedule',
            'biometric_user_id',
            'sss_number', 'philhealth_number', 'pagibig_number', 'tin_number',
            'emergency_contact_name', 'emergency_contact_phone',
        ]
        widgets = {
            'date_hired': forms.DateInput(attrs={'type': 'date'}),
            'address': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Lazy import avoids circular dependency (attendance.models → employees.models)
        from attendance.models import WorkSchedule
        self.fields['work_schedule'].queryset = WorkSchedule.objects.filter(is_active=True)
        self.fields['work_schedule'].required = False
        _bootstrap(self)
