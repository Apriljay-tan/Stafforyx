from django.contrib import admin

from .models import OvertimeRequest


@admin.register(OvertimeRequest)
class OvertimeRequestAdmin(admin.ModelAdmin):
    list_display = (
        'employee', 'company', 'date', 'requested_hours',
        'approved_hours', 'status', 'source', 'reviewed_by', 'reviewed_at',
    )
    list_filter = ('company', 'status', 'source')
    search_fields = (
        'employee__first_name', 'employee__last_name',
        'employee__employee_id', 'company__name',
    )
    readonly_fields = ('created_at', 'updated_at')
    date_hierarchy = 'date'
