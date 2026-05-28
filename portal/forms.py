from decimal import Decimal

from django import forms

from leaves.models import LeaveRequest, LeaveType

from .models import IncidentReport


def _bootstrap(form):
    for field in form.fields.values():
        widget = field.widget
        if isinstance(widget, forms.CheckboxInput):
            widget.attrs.setdefault('class', 'form-check-input')
        elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
            widget.attrs.setdefault('class', 'form-select')
        else:
            widget.attrs.setdefault('class', 'form-control')


class PortalLeaveRequestForm(forms.ModelForm):
    class Meta:
        model = LeaveRequest
        fields = ['leave_type', 'start_date', 'end_date', 'reason']
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
            'reason': forms.Textarea(attrs={'rows': 4}),
        }

    def __init__(self, *args, employee=None, **kwargs):
        super().__init__(*args, **kwargs)
        if employee:
            self.fields['leave_type'].queryset = LeaveType.objects.filter(company=employee.company)
        _bootstrap(self)

    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data.get('start_date')
        end = cleaned_data.get('end_date')
        if start and end:
            if end < start:
                raise forms.ValidationError('End date must not be earlier than start date.')
            cleaned_data['_total_days'] = Decimal((end - start).days + 1)
        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.total_days = self.cleaned_data.get('_total_days', Decimal('1'))
        if commit:
            instance.save()
        return instance


class PortalIncidentReportForm(forms.ModelForm):
    class Meta:
        model = IncidentReport
        fields = ['incident_date', 'incident_time', 'title', 'description', 'location', 'witnesses']
        widgets = {
            'incident_date': forms.DateInput(attrs={'type': 'date'}),
            'incident_time': forms.TimeInput(attrs={'type': 'time'}),
            'description': forms.Textarea(attrs={'rows': 5}),
            'witnesses': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrap(self)
