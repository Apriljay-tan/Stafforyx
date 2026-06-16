from django.contrib.auth.models import User
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from companies.models import Company


class Notification(models.Model):
    TYPE_LEAVE_REQUEST = 'leave_request'
    TYPE_OVERTIME_REQUEST = 'overtime_request'
    TYPE_CASH_ADVANCE_REQUEST = 'cash_advance_request'
    TYPE_PAYROLL = 'payroll'
    TYPE_ATTENDANCE = 'attendance'
    TYPE_DOCUMENT = 'document'
    TYPE_ANNOUNCEMENT = 'announcement'
    TYPE_SYSTEM = 'system'

    NOTIFICATION_TYPE_CHOICES = [
        (TYPE_LEAVE_REQUEST, 'Leave request'),
        (TYPE_OVERTIME_REQUEST, 'Overtime request'),
        (TYPE_CASH_ADVANCE_REQUEST, 'Cash advance request'),
        (TYPE_PAYROLL, 'Payroll'),
        (TYPE_ATTENDANCE, 'Attendance'),
        (TYPE_DOCUMENT, 'Document'),
        (TYPE_ANNOUNCEMENT, 'Announcement'),
        (TYPE_SYSTEM, 'System'),
    ]

    recipient = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='notifications',
    )
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name='notifications',
    )
    notification_type = models.CharField(
        max_length=40,
        choices=NOTIFICATION_TYPE_CHOICES,
    )
    title = models.CharField(max_length=160)
    message = models.TextField(blank=True)
    target_url = models.CharField(max_length=500, blank=True)
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    object_id = models.PositiveBigIntegerField(null=True, blank=True)
    content_object = GenericForeignKey('content_type', 'object_id')
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient', 'is_read', 'notification_type']),
            models.Index(fields=['recipient', 'is_read', 'created_at']),
            models.Index(fields=['company', 'notification_type', 'is_read']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['recipient', 'notification_type', 'content_type', 'object_id'],
                name='unique_notification_per_recipient_object_type',
            ),
        ]

    def __str__(self):
        return f'{self.recipient} - {self.title}'
