import os

from django.db import models
from django.contrib.auth.models import User
from companies.models import Company
from employees.models import Department, Employee


class Announcement(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='announcements')
    title = models.CharField(max_length=255)
    # Rich HTML body (sanitised on save). May be empty if an attachment carries the content.
    content = models.TextField(blank=True)
    attachment = models.FileField(
        upload_to='announcements/attachments/', null=True, blank=True,
        help_text='Optional PDF or Word file to share with this announcement.',
    )
    target_department = models.ForeignKey(
        Department, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='announcements'
    )
    is_active = models.BooleanField(default=True)
    posted_by = models.ForeignKey(
        User, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='announcements'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title

    @property
    def attachment_name(self):
        return os.path.basename(self.attachment.name) if self.attachment else ''


class AnnouncementSeen(models.Model):
    """
    Tracks when an employee last opened their portal notifications, so the bell
    badge can count announcements posted since then. One row per employee.
    """
    employee = models.OneToOneField(
        Employee, on_delete=models.CASCADE, related_name='announcement_seen'
    )
    last_seen_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.employee} — seen {self.last_seen_at}'
