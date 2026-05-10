from django.contrib import admin
from .models import Announcement


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ('title', 'company', 'target_department', 'is_active', 'posted_by', 'created_at')
    search_fields = ('title', 'content', 'company__name')
    list_filter = ('company', 'is_active', 'target_department')
    readonly_fields = ('created_at', 'updated_at')
