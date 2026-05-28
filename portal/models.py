from django.db import models

from companies.models import Company
from employees.models import Employee


class IncidentReport(models.Model):
    STATUS_CHOICES = [
        ('submitted', 'Submitted'),
        ('under_review', 'Under Review'),
        ('resolved', 'Resolved'),
        ('rejected', 'Rejected'),
    ]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='incident_reports')
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='incident_reports')
    incident_date = models.DateField()
    incident_time = models.TimeField(null=True, blank=True)
    title = models.CharField(max_length=200)
    description = models.TextField()
    location = models.CharField(max_length=200)
    witnesses = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='submitted')
    admin_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.employee} — {self.title} ({self.incident_date})"
