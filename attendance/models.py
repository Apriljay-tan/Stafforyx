from django.db import models
from companies.models import Company
from employees.models import Employee


class WorkSchedule(models.Model):
    company = models.ForeignKey(
        Company, on_delete=models.CASCADE,
        null=True, blank=True, related_name='work_schedules',
    )
    name = models.CharField(max_length=100)
    start_time = models.TimeField()
    end_time = models.TimeField()
    grace_minutes = models.PositiveIntegerField(default=15)
    break_minutes = models.PositiveIntegerField(default=60)
    required_hours = models.DecimalField(max_digits=4, decimal_places=2, default=8.00)
    overtime_after = models.TimeField(
        null=True, blank=True,
        help_text='Overtime counted after this time. Leave blank to use End Time.',
    )
    work_monday = models.BooleanField(default=True)
    work_tuesday = models.BooleanField(default=True)
    work_wednesday = models.BooleanField(default=True)
    work_thursday = models.BooleanField(default=True)
    work_friday = models.BooleanField(default=True)
    work_saturday = models.BooleanField(default=False)
    work_sunday = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return (
            f"{self.name} "
            f"({self.start_time.strftime('%I:%M %p')} – {self.end_time.strftime('%I:%M %p')})"
        )


class AttendanceRecord(models.Model):
    STATUS_CHOICES = [
        ('present', 'Present'),
        ('absent', 'Absent'),
        ('late', 'Late'),
        ('half_day', 'Half Day'),
        ('on_leave', 'On Leave'),
    ]
    COMPUTED_STATUS_CHOICES = [
        ('present',     'Present'),
        ('late',        'Late'),
        ('undertime',   'Undertime'),
        ('overtime',    'Overtime'),
        ('absent',      'Absent'),
        ('incomplete',  'Incomplete'),
        ('no_schedule', 'No Schedule'),
        ('rest_day',    'Rest Day'),
    ]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='attendance_records')
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='attendance_records')
    date = models.DateField()
    time_in = models.TimeField(null=True, blank=True)
    time_out = models.TimeField(null=True, blank=True)
    break_minutes = models.PositiveIntegerField(default=0)
    total_hours = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    late_minutes = models.PositiveIntegerField(default=0)
    undertime_minutes = models.PositiveIntegerField(default=0)
    overtime_hours = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    overtime_minutes = models.PositiveIntegerField(default=0)
    total_work_minutes = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='present')
    computed_status = models.CharField(max_length=20, blank=True, default='')
    remarks = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date', 'employee']
        unique_together = ('employee', 'date')

    def __str__(self):
        return f"{self.employee} — {self.date} ({self.get_status_display()})"
