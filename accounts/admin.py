from django.contrib import admin

from .models import UserCompanyAccess, UserProfile


@admin.register(UserCompanyAccess)
class UserCompanyAccessAdmin(admin.ModelAdmin):
    list_display = ('user', 'company', 'role', 'is_active', 'created_at')
    list_filter = ('role', 'is_active', 'company')
    search_fields = ('user__username', 'user__email', 'company__name')
    autocomplete_fields = []


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'role', 'company', 'is_active_stafforyx')
    list_filter = ('role', 'company', 'is_active_stafforyx')
    search_fields = ('user__username', 'user__email', 'company__name')
    fieldsets = (
        ('User Access', {
            'fields': ('user', 'company', 'employee', 'role', 'is_active_stafforyx'),
        }),
        ('Module Permissions', {
            'fields': (
                'can_access_dashboard', 'can_manage_employees',
                'can_manage_attendance', 'can_manage_leaves',
                'can_manage_payroll', 'can_manage_documents',
                'can_manage_announcements', 'can_view_reports',
                'can_export_data', 'can_manage_users',
                'can_manage_settings', 'can_manage_license',
            ),
        }),
    )
