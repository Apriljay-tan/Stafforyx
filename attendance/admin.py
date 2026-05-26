from django.contrib import admin
from .models import AttendanceRecord, BiometricDevice, BiometricLog, WorkSchedule


@admin.register(WorkSchedule)
class WorkScheduleAdmin(admin.ModelAdmin):
    list_display = ('name', 'company', 'start_time', 'end_time', 'grace_minutes', 'required_hours', 'is_active')
    list_filter = ('is_active', 'company')
    search_fields = ('name',)
    readonly_fields = ('created_at', 'updated_at')


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = (
        'employee', 'date', 'time_in', 'time_out',
        'total_hours', 'late_minutes', 'overtime_hours',
        'computed_status', 'status',
    )
    search_fields = (
        'employee__first_name', 'employee__last_name', 'employee__employee_id'
    )
    list_filter = ('company', 'status', 'computed_status', 'date')
    readonly_fields = ('created_at', 'updated_at')
    date_hierarchy = 'date'


@admin.register(BiometricDevice)
class BiometricDeviceAdmin(admin.ModelAdmin):
    # api_key intentionally excluded from list_display
    list_display = (
        'company', 'name', 'device_code', 'serial_number',
        'location', 'device_type', 'ip_address', 'is_active', 'last_sync_at',
    )
    list_filter = ('company', 'is_active', 'device_type')
    search_fields = ('name', 'device_code', 'serial_number', 'company__name')
    readonly_fields = ('created_at', 'updated_at', 'last_sync_at')
    fieldsets = (
        ('Device Identity', {
            'fields': ('company', 'name', 'device_code', 'serial_number', 'device_type', 'location'),
        }),
        ('Network', {
            'fields': ('ip_address', 'port'),
        }),
        ('Security', {
            'classes': ('collapse',),
            'fields': ('api_key',),
            'description': 'Keep the API key confidential. It is used for future sync authentication.',
        }),
        ('Status', {
            'fields': ('is_active', 'last_sync_at', 'notes'),
        }),
        ('Timestamps', {
            'classes': ('collapse',),
            'fields': ('created_at', 'updated_at'),
        }),
    )


@admin.register(BiometricLog)
class BiometricLogAdmin(admin.ModelAdmin):
    list_display = (
        'company', 'employee', 'biometric_user_id',
        'punch_time', 'punch_type', 'processed', 'device',
    )
    list_filter = ('company', 'punch_type', 'processed', 'device')
    search_fields = (
        'biometric_user_id',
        'employee__first_name', 'employee__last_name', 'employee__employee_id',
        'device__name', 'device__device_code',
    )
    readonly_fields = ('created_at', 'processed_at', 'raw_payload')
    date_hierarchy = 'punch_time'
    fieldsets = (
        ('Source', {
            'fields': ('company', 'device', 'employee', 'biometric_user_id'),
        }),
        ('Punch Data', {
            'fields': ('punch_time', 'punch_type', 'raw_status_code'),
        }),
        ('Raw Payload', {
            'classes': ('collapse',),
            'fields': ('raw_payload',),
        }),
        ('Processing', {
            'fields': ('processed', 'processed_at', 'attendance_record', 'error_message'),
        }),
        ('Timestamps', {
            'classes': ('collapse',),
            'fields': ('created_at',),
        }),
    )
