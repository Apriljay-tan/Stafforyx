from django import forms

from .models import AttendanceRecord


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
