from django.contrib import admin

from .models import IncidentReport


@admin.register(IncidentReport)
class IncidentReportAdmin(admin.ModelAdmin):
    list_display = ('employee', 'company', 'title', 'incident_date', 'status', 'created_at')
    list_filter = ('status', 'company', 'incident_date')
    search_fields = ('employee__first_name', 'employee__last_name', 'title', 'description')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        (None, {
            'fields': ('employee', 'company', 'status'),
        }),
        ('Incident Details', {
            'fields': ('incident_date', 'incident_time', 'title', 'description', 'location', 'witnesses'),
        }),
        ('Admin', {
            'fields': ('admin_notes', 'created_at', 'updated_at'),
        }),
    )
