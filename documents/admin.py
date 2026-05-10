from django.contrib import admin
from .models import EmployeeDocument


@admin.register(EmployeeDocument)
class EmployeeDocumentAdmin(admin.ModelAdmin):
    list_display = ('title', 'employee', 'document_type', 'expiration_date', 'uploaded_by', 'created_at')
    search_fields = (
        'title', 'employee__first_name', 'employee__last_name', 'employee__employee_id'
    )
    list_filter = ('company', 'document_type')
    readonly_fields = ('created_at', 'updated_at')
