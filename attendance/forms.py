from django import forms

from .models import AttendanceLocation, AttendanceRecord, WorkSchedule


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
            'grace_minutes', 'break_minutes', 'required_hours',
            'work_monday', 'work_tuesday', 'work_wednesday', 'work_thursday',
            'work_friday', 'work_saturday', 'work_sunday',
            'is_active',
        ]
        widgets = {
            'start_time':     forms.TimeInput(attrs={'type': 'time'}),
            'end_time':       forms.TimeInput(attrs={'type': 'time'}),
            'overtime_after': forms.TimeInput(attrs={'type': 'time'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrap(self)
