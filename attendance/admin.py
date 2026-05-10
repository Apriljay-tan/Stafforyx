from django.contrib import admin
from .models import AttendanceRecord


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = (
        'employee', 'date', 'time_in', 'time_out',
        'total_hours', 'late_minutes', 'overtime_hours', 'status'
    )
    search_fields = (
        'employee__first_name', 'employee__last_name', 'employee__employee_id'
    )
    list_filter = ('company', 'status', 'date')
    readonly_fields = ('created_at', 'updated_at')
    date_hierarchy = 'date'
