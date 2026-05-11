from django.contrib import admin
from .models import AttendanceRecord, WorkSchedule


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
