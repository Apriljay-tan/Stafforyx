from django.contrib import admin
from .models import (
    AttendanceLocation, AttendancePortalLog, AttendanceRecord,
    BiometricDevice, BiometricLog,
    EmployeeDailySchedule, ShiftTemplate, WorkSchedule,
)


@admin.register(WorkSchedule)
class WorkScheduleAdmin(admin.ModelAdmin):
    list_display = ('name', 'company', 'start_time', 'end_time', 'grace_minutes', 'required_hours', 'is_active')
    list_filter = ('is_active', 'company')
    search_fields = ('name',)
    readonly_fields = ('created_at', 'updated_at')


@admin.register(ShiftTemplate)
class ShiftTemplateAdmin(admin.ModelAdmin):
    list_display = ('company', 'name', 'start_time', 'end_time', 'break_minutes', 'grace_minutes', 'is_overnight', 'is_active')
    list_filter = ('company', 'is_active', 'is_overnight')
    search_fields = ('name', 'company__name')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('Shift', {'fields': ('company', 'name', 'start_time', 'end_time', 'is_overnight', 'is_active', 'notes')}),
        ('Timing Rules', {'fields': ('break_minutes', 'grace_minutes', 'allow_early_clock_in_minutes', 'overtime_after_minutes')}),
        ('Timestamps', {'classes': ('collapse',), 'fields': ('created_at', 'updated_at')}),
    )


@admin.register(EmployeeDailySchedule)
class EmployeeDailyScheduleAdmin(admin.ModelAdmin):
    list_display = ('schedule_date', 'employee', 'company', 'shift_template', 'is_rest_day', 'source', 'created_by')
    list_filter = ('company', 'source', 'is_rest_day', 'shift_template')
    search_fields = ('employee__first_name', 'employee__last_name', 'employee__employee_id', 'shift_template__name')
    date_hierarchy = 'schedule_date'
    readonly_fields = ('created_at', 'updated_at', 'created_by')
    fieldsets = (
        ('Assignment', {'fields': ('company', 'employee', 'schedule_date', 'source', 'created_by')}),
        ('Shift', {'fields': ('shift_template', 'is_rest_day', 'reason')}),
        ('Custom Override', {
            'classes': ('collapse',),
            'fields': ('custom_start_time', 'custom_end_time', 'break_minutes', 'grace_minutes'),
            'description': 'Use these to override the shift template times for this specific date.',
        }),
        ('Timestamps', {'classes': ('collapse',), 'fields': ('created_at', 'updated_at')}),
    )


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


@admin.register(AttendanceLocation)
class AttendanceLocationAdmin(admin.ModelAdmin):
    list_display = ('company', 'name', 'ip_address', 'cidr_range', 'is_active', 'require_selfie', 'require_gps')
    list_filter = ('company', 'is_active')
    search_fields = ('company__name', 'name', 'ip_address', 'cidr_range')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('Location', {
            'fields': ('company', 'name', 'address', 'notes'),
        }),
        ('Network', {
            'fields': ('ip_address', 'cidr_range'),
            'description': (
                'At least one of IP Address or CIDR Range is required. '
                'The server checks the employee\'s visible public IP against these values.'
            ),
        }),
        ('Options', {
            'fields': ('is_active', 'require_selfie', 'require_gps'),
        }),
        ('Timestamps', {
            'classes': ('collapse',),
            'fields': ('created_at', 'updated_at'),
        }),
    )


@admin.register(AttendancePortalLog)
class AttendancePortalLogAdmin(admin.ModelAdmin):
    list_display = (
        'created_at', 'company', 'employee', 'action', 'status',
        'ip_address', 'attendance_location',
    )
    list_filter = ('company', 'status', 'action', 'attendance_location')
    search_fields = (
        'employee__first_name', 'employee__last_name', 'employee__employee_id',
        'ip_address', 'company__name',
    )
    readonly_fields = (
        'company', 'employee', 'attendance_location', 'attendance_record',
        'action', 'ip_address', 'user_agent', 'status', 'blocked_reason',
        'gps_latitude', 'gps_longitude', 'created_at',
    )
    date_hierarchy = 'created_at'
    fieldsets = (
        ('Who & When', {
            'fields': ('company', 'employee', 'created_at'),
        }),
        ('Action', {
            'fields': ('action', 'status', 'blocked_reason'),
        }),
        ('Network', {
            'fields': ('ip_address', 'attendance_location', 'user_agent'),
        }),
        ('Result', {
            'fields': ('attendance_record',),
        }),
        ('GPS (placeholder)', {
            'classes': ('collapse',),
            'fields': ('gps_latitude', 'gps_longitude'),
        }),
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
