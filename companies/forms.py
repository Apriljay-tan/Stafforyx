from django import forms
from .models import Company


def _bootstrap(form):
    for field in form.fields.values():
        widget = field.widget
        if isinstance(widget, forms.CheckboxInput):
            widget.attrs.setdefault('class', 'form-check-input')
        elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
            widget.attrs.setdefault('class', 'form-select form-select-sm')
        else:
            widget.attrs.setdefault('class', 'form-control form-control-sm')


class CompanyPayslipSettingsForm(forms.ModelForm):
    class Meta:
        model = Company
        fields = [
            'payslip_company_display_name',
            'payslip_company_address',
            'payslip_template_style',
            'payslip_accent_color',
            'payslip_show_company_logo',
            'payslip_show_rates',
            'payslip_show_attendance_summary',
            'payslip_show_overtime_breakdown',
            'default_overtime_multiplier',
            'payslip_show_received_by',
            'payslip_prepared_by_name',
            'payslip_prepared_by_title',
            'payslip_prepared_by_signature',
            'payslip_footer_note',
            'attendance_selfie_retention_days',
            'attendance_portal_log_retention_days',
            'attendance_log_page_opened_events',
            'attendance_log_blocked_attempts',
            'attendance_log_clock_actions',
            'attendance_auto_delete_portal_logs',
            'attendance_qr_validation_enabled',
            'attendance_qr_token_lifetime_seconds',
            'attendance_qr_token_retention_days',
            'attendance_auto_delete_qr_tokens',
            'attendance_qr_scan_log_retention_days',
            'attendance_auto_delete_qr_scan_logs',
        ]
        widgets = {
            'payslip_company_address': forms.Textarea(attrs={'rows': 3}),
            'payslip_footer_note': forms.Textarea(attrs={'rows': 3}),
            'payslip_accent_color': forms.TextInput(attrs={'type': 'color', 'style': 'width:80px;height:36px;padding:2px 4px;'}),
            'payslip_prepared_by_signature': forms.ClearableFileInput(attrs={'accept': 'image/*'}),
            'attendance_qr_token_lifetime_seconds': forms.NumberInput(attrs={'min': 30, 'max': 300}),
            'attendance_qr_token_retention_days': forms.NumberInput(attrs={'min': 1}),
            'attendance_qr_scan_log_retention_days': forms.NumberInput(attrs={'min': 1}),
            'default_overtime_multiplier': forms.NumberInput(attrs={'min': '1.0', 'max': '5.0', 'step': '0.05'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrap(self)
        # color input needs its own class, not form-control-sm
        self.fields['payslip_accent_color'].widget.attrs['class'] = 'form-control form-control-color'
        self.fields['payslip_prepared_by_signature'].required = False
