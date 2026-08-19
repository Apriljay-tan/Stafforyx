from django.contrib import admin
from .models import Department, Position, Employee


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ('name', 'company', 'created_at')
    search_fields = ('name', 'company__name')
    list_filter = ('company',)
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_display = ('title', 'department', 'company', 'created_at')
    search_fields = ('title', 'department__name', 'company__name')
    list_filter = ('company', 'department')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = (
        'employee_id', 'last_name', 'first_name', 'company',
        'department', 'position', 'employment_type', 'status',
        'attendance_policy_type', 'biometric_user_id',
    )
    search_fields = (
        'employee_id', 'biometric_user_id',
        'first_name', 'last_name', 'email', 'phone',
    )
    list_filter = ('company', 'department', 'employment_type', 'status', 'attendance_policy_type')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('Basic Information', {
            'fields': (
                'company', 'user', 'employee_id', 'photo',
                'first_name', 'middle_name', 'last_name',
                'email', 'phone', 'address',
            )
        }),
        ('Employment Details', {
            'fields': (
                'date_hired', 'department', 'position',
                'employment_type', 'status', 'pay_basis', 'basic_salary',
                'daily_rate', 'daily_allowance', 'allowance_frequency',
                'deduct_undertime',
                'biometric_user_id',
            )
        }),
        ('Attendance Policy', {
            'fields': (
                'work_schedule', 'attendance_policy_type', 'required_daily_hours',
                'default_break_minutes', 'flexible_overtime_grace_minutes',
                'overtime_policy', 'overtime_multiplier',
                'flexible_day_offs',
                'flexible_schedule_enabled', 'allowed_clock_in_from',
                'allowed_clock_in_until',
                'night_differential_enabled', 'night_differential_percentage',
                'night_differential_start_time', 'night_differential_end_time',
                'allow_other_registered_locations',
            )
        }),
        ('Government IDs', {
            'fields': ('sss_number', 'philhealth_number', 'pagibig_number', 'tin_number'),
            'classes': ('collapse',),
        }),
        ('Emergency Contact', {
            'fields': ('emergency_contact_name', 'emergency_contact_phone'),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )
