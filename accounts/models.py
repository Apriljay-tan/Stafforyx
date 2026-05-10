from django.contrib.auth.models import User
from django.db import models

from companies.models import Company
from employees.models import Employee


class UserProfile(models.Model):
    ROLE_CHOICES = [
        ('super_admin', 'Super Admin'),
        ('hr_admin', 'HR Admin'),
        ('manager', 'Manager'),
        ('employee', 'Employee'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='stafforyx_profile')
    company = models.ForeignKey(
        Company, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='user_profiles'
    )
    employee = models.ForeignKey(
        Employee, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='user_profiles'
    )
    role = models.CharField(max_length=30, choices=ROLE_CHOICES, default='employee')
    is_active_stafforyx = models.BooleanField(default=True)

    can_access_dashboard = models.BooleanField(default=True)
    can_manage_employees = models.BooleanField(default=False)
    can_manage_attendance = models.BooleanField(default=False)
    can_manage_leaves = models.BooleanField(default=False)
    can_manage_payroll = models.BooleanField(default=False)
    can_manage_documents = models.BooleanField(default=False)
    can_manage_announcements = models.BooleanField(default=False)
    can_view_reports = models.BooleanField(default=False)
    can_export_data = models.BooleanField(default=False)
    can_manage_users = models.BooleanField(default=False)
    can_manage_settings = models.BooleanField(default=False)
    can_manage_license = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['user__username']

    def __str__(self):
        return f'{self.user.username} - {self.get_role_display()}'
