from django.contrib import admin, messages as dj_messages
from .models import License

_ALL_FIELDS = (
    'license_id', 'license_key', 'client_name', 'company', 'company_name',
    'plan', 'status', 'valid_from', 'valid_until', 'max_employees',
    'machine_id', 'notes', 'created_at', 'updated_at',
)


@admin.register(License)
class LicenseAdmin(admin.ModelAdmin):
    list_display  = ('client_name', 'display_company', 'plan', 'status',
                     'valid_until', 'max_employees', 'machine_id', 'created_at')
    list_filter   = ('plan', 'status')
    search_fields = ('client_name', 'license_key', 'company__name',
                     'machine_id', 'license_id')
    readonly_fields = _ALL_FIELDS

    # ── Disable all write operations ─────────────────────────────────────────

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return True

    # ── Show a reminder on every visit to the license list ───────────────────

    def changelist_view(self, request, extra_context=None):
        dj_messages.info(
            request,
            'Licenses must be activated using a signed license key. '
            'Manual license creation and editing are disabled.',
        )
        return super().changelist_view(request, extra_context)
