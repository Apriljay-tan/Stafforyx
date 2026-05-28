from django.contrib import admin
from .models import Company


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'phone', 'status', 'subscription_plan', 'created_at')
    search_fields = ('name', 'email', 'phone')
    list_filter = ('status', 'subscription_plan')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        (None, {
            'fields': ('name', 'email', 'phone', 'address', 'logo', 'status', 'subscription_plan'),
        }),
        ('Payslip Settings', {
            'classes': ('collapse',),
            'fields': (
                'payslip_company_display_name', 'payslip_company_address',
                'payslip_template_style', 'payslip_accent_color',
                'payslip_show_company_logo', 'payslip_show_rates',
                'payslip_show_attendance_summary', 'payslip_show_overtime_breakdown',
                'payslip_show_received_by', 'payslip_footer_note',
            ),
        }),
        ('Attendance Settings', {
            'classes': ('collapse',),
            'fields': ('attendance_selfie_retention_days',),
        }),
        ('Timestamps', {
            'classes': ('collapse',),
            'fields': ('created_at', 'updated_at'),
        }),
    )
