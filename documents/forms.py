from django import forms

from .models import EmployeeDocument


def _bootstrap(form):
    for field in form.fields.values():
        widget = field.widget
        if isinstance(widget, forms.CheckboxInput):
            widget.attrs.setdefault('class', 'form-check-input')
        elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
            widget.attrs.setdefault('class', 'form-select')
        else:
            widget.attrs.setdefault('class', 'form-control')


class EmployeeDocumentForm(forms.ModelForm):
    class Meta:
        model = EmployeeDocument
        fields = [
            'company', 'employee', 'title', 'document_type',
            'file', 'expiration_date', 'notes',
        ]
        widgets = {
            'expiration_date': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrap(self)
