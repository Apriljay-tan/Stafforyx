from django.db import models
from companies.models import Company
from employees.models import Employee


class AttendanceRecord(models.Model):
    STATUS_CHOICES = [
        ('present', 'Present'),
        ('absent', 'Absent'),
        ('late', 'Late'),
        ('half_day', 'Half Day'),
        ('on_leave', 'On Leave'),
    ]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='attendance_records')
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='attendance_records')
    date = models.DateField()
    time_in = models.TimeField(null=True, blank=True)
    time_out = models.TimeField(null=True, blank=True)
    break_minutes = models.PositiveIntegerField(default=0)
    total_hours = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    late_minutes = models.PositiveIntegerField(default=0)
    overtime_hours = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='present')
    remarks = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date', 'employee']
        unique_together = ('employee', 'date')

    def __str__(self):
        return f"{self.employee} — {self.date} ({self.get_status_display()})"
