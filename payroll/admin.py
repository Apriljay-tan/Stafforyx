from django.contrib import admin
from .models import PayrollPeriod, PayrollRecord


@admin.register(PayrollPeriod)
class PayrollPeriodAdmin(admin.ModelAdmin):
    list_display = ('name', 'company', 'start_date', 'end_date', 'status', 'created_at')
    search_fields = ('name', 'company__name')
    list_filter = ('company', 'status')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(PayrollRecord)
class PayrollRecordAdmin(admin.ModelAdmin):
    list_display = ('employee', 'payroll_period', 'basic_pay', 'gross_pay', 'net_pay', 'status')
    search_fields = (
        'employee__first_name', 'employee__last_name', 'employee__employee_id'
    )
    list_filter = ('company', 'status', 'payroll_period')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('Record Info', {
            'fields': ('company', 'payroll_period', 'employee', 'status'),
        }),
        ('Earnings', {
            'fields': ('basic_pay', 'allowances', 'overtime_pay', 'gross_pay'),
        }),
        ('Deductions', {
            'fields': (
                'sss_deduction', 'philhealth_deduction', 'pagibig_deduction',
                'tax_deduction', 'late_deduction', 'absence_deduction', 'other_deductions',
            ),
        }),
        ('Net Pay', {
            'fields': ('net_pay',),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )
