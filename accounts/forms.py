from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from companies.models import Company

from .models import UserProfile


def _bootstrap(form):
    for field in form.fields.values():
        widget = field.widget
        if isinstance(widget, forms.CheckboxInput):
            widget.attrs.setdefault('class', 'form-check-input')
        elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
            widget.attrs.setdefault('class', 'form-select')
        else:
            widget.attrs.setdefault('class', 'form-control')


class StafforyxUserCreationForm(UserCreationForm):
    email = forms.EmailField(required=False)
    first_name = forms.CharField(required=False)
    last_name = forms.CharField(required=False)

    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name', 'password1', 'password2']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrap(self)


class UserProfileForm(forms.ModelForm):
    managed_companies = forms.ModelMultipleChoiceField(
        queryset=Company.objects.order_by('name'),
        required=False,
        widget=forms.SelectMultiple(attrs={'size': 8}),
        label='Managed companies / branches',
        help_text=(
            'Choose every company this user may view and manage. '
            'HR admins need one row per branch to see employees and attendance.'
        ),
    )

    class Meta:
        model = UserProfile
        fields = [
            'company', 'employee', 'role', 'is_active_stafforyx',
            'can_access_dashboard', 'can_manage_employees',
            'can_manage_attendance', 'can_manage_leaves',
            'can_manage_payroll', 'can_manage_documents',
            'can_manage_announcements', 'can_view_reports',
            'can_export_data', 'can_manage_users',
            'can_manage_settings', 'can_manage_license',
        ]

    def __init__(self, *args, **kwargs):
        managed_user = kwargs.pop('managed_user', None)
        super().__init__(*args, **kwargs)
        _bootstrap(self)
        if managed_user is not None:
            from .company_access_sync import get_managed_company_ids
            self.fields['managed_companies'].initial = get_managed_company_ids(managed_user)
        elif self.instance and self.instance.pk:
            from .company_access_sync import get_managed_company_ids
            self.fields['managed_companies'].initial = get_managed_company_ids(
                self.instance.user,
            )
        elif self.instance and self.instance.company_id:
            self.fields['managed_companies'].initial = [self.instance.company_id]

    def clean(self):
        cleaned = super().clean()
        managed = cleaned.get('managed_companies')
        company = cleaned.get('company')
        if managed:
            cleaned['company'] = managed[0]
        elif company:
            cleaned['managed_companies'] = Company.objects.filter(pk=company.pk)
        return cleaned
