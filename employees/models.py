from django.db import models
from django.contrib.auth.models import User
from companies.models import Company


class Department(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='departments')
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        unique_together = ('company', 'name')

    def __str__(self):
        return f"{self.name} — {self.company.name}"


class Position(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='positions')
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name='positions')
    title = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['title']

    def __str__(self):
        return f"{self.title} ({self.department.name})"


class Employee(models.Model):
    EMPLOYMENT_TYPE_CHOICES = [
        ('regular', 'Regular'),
        ('probationary', 'Probationary'),
        ('contractual', 'Contractual'),
        ('part_time', 'Part-time'),
        ('intern', 'Intern'),
    ]
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('resigned', 'Resigned'),
        ('terminated', 'Terminated'),
        ('inactive', 'Inactive'),
    ]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='employees')
    user = models.OneToOneField(
        User, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='employee_profile'
    )
    employee_id = models.CharField(max_length=30)
    first_name = models.CharField(max_length=100)
    middle_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=30, blank=True)
    address = models.TextField(blank=True)
    date_hired = models.DateField()
    department = models.ForeignKey(
        Department, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='employees'
    )
    position = models.ForeignKey(
        Position, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='employees'
    )
    employment_type = models.CharField(max_length=20, choices=EMPLOYMENT_TYPE_CHOICES, default='regular')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    basic_salary = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    biometric_user_id = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text='ID number used by the biometric attendance device',
    )
    sss_number = models.CharField(max_length=30, blank=True)
    philhealth_number = models.CharField(max_length=30, blank=True)
    pagibig_number = models.CharField(max_length=30, blank=True)
    tin_number = models.CharField(max_length=30, blank=True)
    emergency_contact_name = models.CharField(max_length=150, blank=True)
    emergency_contact_phone = models.CharField(max_length=30, blank=True)
    photo = models.ImageField(upload_to='employees/photos/', blank=True, null=True)
    # String reference avoids circular import (attendance.models imports Employee)
    work_schedule = models.ForeignKey(
        'attendance.WorkSchedule',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='employees',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['last_name', 'first_name']
        unique_together = ('company', 'employee_id')

    def __str__(self):
        return f"{self.last_name}, {self.first_name} [{self.employee_id}]"

    @property
    def full_name(self):
        parts = [self.first_name, self.middle_name, self.last_name]
        return ' '.join(p for p in parts if p)
