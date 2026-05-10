from django.contrib import admin
from .models import License


@admin.register(License)
class LicenseAdmin(admin.ModelAdmin):
    list_display = ('client_name', 'company', 'plan', 'status', 'valid_until', 'max_employees')
    list_filter = ('plan', 'status', 'valid_until')
    search_fields = ('client_name', 'license_key', 'company__name', 'machine_id')
    readonly_fields = ('created_at', 'updated_at')
