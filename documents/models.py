from django.db import models
from django.contrib.auth.models import User
from companies.models import Company
from employees.models import Employee


class EmployeeDocument(models.Model):
    DOCUMENT_TYPE_CHOICES = [
        ('contract', 'Contract'),
        ('government_id', 'Government ID'),
        ('certificate', 'Certificate'),
        ('memo', 'Memo'),
        ('clearance', 'Clearance'),
        ('other', 'Other'),
    ]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='documents')
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='documents')
    title = models.CharField(max_length=255)
    document_type = models.CharField(max_length=30, choices=DOCUMENT_TYPE_CHOICES, default='other')
    file = models.FileField(upload_to='documents/employee/%Y/%m/')
    expiration_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    uploaded_by = models.ForeignKey(
        User, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='uploaded_documents'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} — {self.employee}"
