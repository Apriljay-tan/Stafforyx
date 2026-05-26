from django.db import models
from companies.models import Company
from employees.models import Employee


class BiometricDevice(models.Model):
    DEVICE_TYPE_CHOICES = [
        ('zkteco',    'ZKTeco'),
        ('hikvision', 'Hikvision'),
        ('dahua',     'Dahua'),
        ('anviz',     'Anviz'),
        ('other',     'Other'),
    ]

    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name='biometric_devices'
    )
    name = models.CharField(max_length=100)
    device_code = models.CharField(
        max_length=50,
        help_text='Short unique code used to identify this device (e.g. HQ-DOOR-01).',
    )
    serial_number = models.CharField(max_length=100, blank=True)
    location = models.CharField(max_length=200, blank=True)
    device_type = models.CharField(
        max_length=30, choices=DEVICE_TYPE_CHOICES, default='zkteco'
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    port = models.PositiveIntegerField(null=True, blank=True)
    # api_key is intentionally excluded from list_display in admin.
    api_key = models.CharField(
        max_length=128, blank=True,
        help_text='Secret key for authenticating future sync requests from this device.',
    )
    is_active = models.BooleanField(default=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['company', 'name']
        unique_together = [('company', 'device_code')]

    def __str__(self):
        return f'{self.company.name} — {self.name} ({self.device_code})'


class BiometricLog(models.Model):
    PUNCH_TYPE_CHOICES = [
        ('unknown',    'Unknown'),
        ('check_in',   'Check In'),
        ('check_out',  'Check Out'),
        ('break_in',   'Break In'),
        ('break_out',  'Break Out'),
    ]

    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name='biometric_logs'
    )
    device = models.ForeignKey(
        BiometricDevice, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='logs'
    )
    # employee is resolved at log-creation time; may be null if id is unrecognised.
    employee = models.ForeignKey(
        Employee, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='biometric_logs'
    )
    # The raw ID string sent by the device — used for matching.
    biometric_user_id = models.CharField(max_length=50)
    punch_time = models.DateTimeField()
    punch_type = models.CharField(
        max_length=20, choices=PUNCH_TYPE_CHOICES, default='unknown'
    )
    raw_status_code = models.CharField(max_length=20, blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)
    processed = models.BooleanField(default=False)
    processed_at = models.DateTimeField(null=True, blank=True)
    attendance_record = models.ForeignKey(
        'AttendanceRecord', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='biometric_logs'
    )
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-punch_time']
        indexes = [
            models.Index(fields=['company', 'punch_time']),
            models.Index(fields=['company', 'biometric_user_id']),
            models.Index(fields=['processed']),
        ]

    def __str__(self):
        emp = self.employee or f'uid:{self.biometric_user_id}'
        return f'{self.company.name} — {emp} @ {self.punch_time:%Y-%m-%d %H:%M} ({self.punch_type})'


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
