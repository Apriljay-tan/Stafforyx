from django.db import models
from django.contrib.auth.models import User
from companies.models import Company
from employees.models import Employee


class LeaveType(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='leave_types')
    name = models.CharField(max_length=100)
    default_days = models.PositiveIntegerField(default=0)
    is_paid = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        unique_together = ('company', 'name')

    def __str__(self):
        label = 'Paid' if self.is_paid else 'Unpaid'
        return f"{self.name} ({label}, {self.default_days}d)"


class LeaveRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
    ]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='leave_requests')
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='leave_requests')
    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT, related_name='leave_requests')
    start_date = models.DateField()
    end_date = models.DateField()
    total_days = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='reviewed_leaves'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    remarks = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.employee} — {self.leave_type.name} ({self.start_date} to {self.end_date})"
