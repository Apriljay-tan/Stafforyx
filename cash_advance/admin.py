from django.contrib import admin

from .models import CashAdvanceRequest


@admin.register(CashAdvanceRequest)
class CashAdvanceRequestAdmin(admin.ModelAdmin):
    list_display = (
        'employee', 'company', 'amount', 'status',
        'requested_release_date', 'approved_by', 'released_by', 'created_at',
    )
    list_filter = ('company', 'status')
    search_fields = (
        'employee__first_name', 'employee__last_name',
        'employee__employee_id', 'company__name',
    )
    readonly_fields = ('created_at', 'updated_at')
    date_hierarchy = 'created_at'
