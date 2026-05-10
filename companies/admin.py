from django.contrib import admin
from .models import Company


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'phone', 'status', 'subscription_plan', 'created_at')
    search_fields = ('name', 'email', 'phone')
    list_filter = ('status', 'subscription_plan')
    readonly_fields = ('created_at', 'updated_at')
