from django.contrib import admin
from .models import LeaveType, LeaveRequest


@admin.register(LeaveType)
class LeaveTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'company', 'default_days', 'is_paid', 'created_at')
    search_fields = ('name', 'company__name')
    list_filter = ('company', 'is_paid')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(LeaveRequest)
class LeaveRequestAdmin(admin.ModelAdmin):
    list_display = (
        'employee', 'leave_type', 'start_date', 'end_date',
        'total_days', 'status', 'reviewed_by'
    )
    search_fields = (
        'employee__first_name', 'employee__last_name', 'employee__employee_id'
    )
    list_filter = ('company', 'status', 'leave_type')
    readonly_fields = ('created_at', 'updated_at')
    date_hierarchy = 'start_date'
