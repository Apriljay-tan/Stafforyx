from django.contrib.auth.models import User
from django.db import models

from companies.models import Company
from employees.models import Employee


class OvertimeRequest(models.Model):
    STATUS_CHOICES = [
        ('pending',       'Pending'),
        ('approved',      'Approved'),
        ('rejected',      'Rejected'),
        ('auto_approved', 'Auto Approved'),
    ]
    SOURCE_CHOICES = [
        ('employee', 'Employee'),
        ('detected', 'Detected'),
        ('hr',       'HR'),
    ]

    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name='overtime_requests'
    )
    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name='overtime_requests'
    )
    date = models.DateField()
    requested_hours = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    approved_hours = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        help_text='Hours actually approved. Blank until reviewed; '
                  'falls back to requested hours on approval.',
    )
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='employee')
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='reviewed_overtime_requests',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    manager_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date', 'employee']
        indexes = [
            models.Index(fields=['company', 'status']),
            models.Index(fields=['employee', 'date']),
        ]

    def __str__(self):
        return f'{self.employee} — {self.date} ({self.get_status_display()})'
