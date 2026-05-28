import datetime
import os
import uuid

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models

from companies.models import Company
from employees.models import Employee


def portal_selfie_upload_path(instance, filename):
    ext = os.path.splitext(filename or '')[1].lower() or '.jpg'
    return f'attendance/portal_selfies/{instance.company_id}/{uuid.uuid4().hex}{ext}'


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


class ShiftTemplate(models.Model):
    """
    A named shift definition (e.g. Morning Shift 6AM-2PM) that can be assigned
    to employees via EmployeeDailySchedule for any date.
    """
    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name='shift_templates'
    )
    name = models.CharField(max_length=100)
    start_time = models.TimeField()
    end_time = models.TimeField()
    break_minutes = models.PositiveIntegerField(default=0)
    grace_minutes = models.PositiveIntegerField(default=10)
    allow_early_clock_in_minutes = models.PositiveIntegerField(
        default=30,
        help_text='Minutes before start_time an employee may clock in via the portal.',
    )
    overtime_after_minutes = models.PositiveIntegerField(
        default=0,
        help_text='Minutes after end_time before overtime is counted. 0 = OT starts at end_time.',
    )
    is_overnight = models.BooleanField(
        default=False,
        help_text='Check if this shift crosses midnight (e.g. 10 PM – 6 AM).',
    )
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['company', 'name']

    def __str__(self):
        return (
            f'{self.company.name} — {self.name} '
            f'({self.start_time.strftime("%I:%M %p")} – {self.end_time.strftime("%I:%M %p")})'
        )

    def clean(self):
        if self.start_time and self.end_time:
            if self.end_time <= self.start_time and not self.is_overnight:
                raise ValidationError(
                    'End time is before or equal to start time. '
                    'Check "Is Overnight" if this shift crosses midnight.'
                )


class EmployeeDailySchedule(models.Model):
    """
    A date-specific schedule assignment for one employee.
    Takes priority over the employee's default WorkSchedule.
    """
    SOURCE_CHOICES = [
        ('manual',    'Manual'),
        ('generated', 'Generated'),
        ('imported',  'Imported'),
    ]

    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name='employee_daily_schedules'
    )
    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name='daily_schedules'
    )
    schedule_date = models.DateField()
    shift_template = models.ForeignKey(
        ShiftTemplate, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='daily_schedules',
    )
    custom_start_time = models.TimeField(
        null=True, blank=True,
        help_text='Override the template start time. Requires custom_end_time.',
    )
    custom_end_time = models.TimeField(
        null=True, blank=True,
        help_text='Override the template end time. Requires custom_start_time.',
    )
    break_minutes = models.PositiveIntegerField(
        null=True, blank=True,
        help_text='Leave blank to use template value.',
    )
    grace_minutes = models.PositiveIntegerField(
        null=True, blank=True,
        help_text='Leave blank to use template value.',
    )
    is_rest_day = models.BooleanField(
        default=False,
        help_text='Employee is not expected to work on this date.',
    )
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='manual')
    reason = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='created_daily_schedules',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['schedule_date', 'employee']
        unique_together = [('employee', 'schedule_date')]

    def __str__(self):
        if self.is_rest_day:
            label = 'Rest Day'
        elif self.shift_template:
            label = self.shift_template.name
        elif self.custom_start_time:
            label = f'{self.custom_start_time.strftime("%I:%M %p")} – {self.custom_end_time.strftime("%I:%M %p") if self.custom_end_time else "?"}'
        else:
            label = 'Unspecified'
        return f'{self.employee} — {self.schedule_date} ({label})'

    def clean(self):
        if self.is_rest_day:
            return
        has_template = bool(self.shift_template_id)
        has_custom = bool(self.custom_start_time) or bool(self.custom_end_time)
        if not has_template and not has_custom:
            raise ValidationError(
                'Either a Shift Template or custom Start/End times must be provided unless this is a Rest Day.'
            )
        if has_custom:
            if not self.custom_start_time or not self.custom_end_time:
                raise ValidationError(
                    'Both custom Start Time and End Time are required when overriding the template.'
                )


class AttendanceLocation(models.Model):
    """
    A registered company/branch network from which employees may clock in/out.
    IP matching is done on the server-visible public IP — not WiFi SSID.
    """
    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name='attendance_locations'
    )
    name = models.CharField(max_length=100, help_text='e.g. Main Office WiFi, Cebu Branch')
    address = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(
        null=True, blank=True,
        help_text='Exact public IP address allowed for clock-in/out.',
    )
    cidr_range = models.CharField(
        max_length=50, blank=True,
        help_text='CIDR range, e.g. 112.198.10.0/24. Leave blank if using exact IP.',
    )
    is_active = models.BooleanField(default=True)
    # Placeholder fields — not yet enforced in portal flow
    require_selfie = models.BooleanField(default=False)
    require_gps = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['company', 'name']

    def __str__(self):
        return f'{self.company.name} — {self.name}'

    def clean(self):
        import ipaddress
        from django.core.exceptions import ValidationError
        if not self.ip_address and not self.cidr_range:
            raise ValidationError('At least one of IP Address or CIDR Range must be provided.')
        if self.cidr_range:
            try:
                ipaddress.ip_network(self.cidr_range, strict=False)
            except ValueError:
                raise ValidationError({'cidr_range': 'Enter a valid CIDR range, e.g. 192.168.1.0/24.'})


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
    SOURCE_CHOICES = [
        ('manual',    'Manual'),
        ('portal',    'WiFi Portal'),
        ('biometric', 'Biometric'),
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
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='manual')
    portal_location = models.ForeignKey(
        'AttendanceLocation', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='attendance_records',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date', 'employee']
        unique_together = ('employee', 'date')

    def __str__(self):
        return f"{self.employee} — {self.date} ({self.get_status_display()})"


class AttendancePortalLog(models.Model):
    """
    Audit log for every interaction with the WiFi/IP portal:
    page opens, blocked attempts, and successful clock events.
    """
    ACTION_CHOICES = [
        ('page_open', 'Page Opened'),
        ('time_in',   'Time In'),
        ('time_out',  'Time Out'),
        ('blocked',   'Blocked'),
    ]
    STATUS_CHOICES = [
        ('allowed',  'Allowed'),
        ('blocked',  'Blocked'),
        ('success',  'Success'),
        ('failed',   'Failed'),
    ]

    company = models.ForeignKey(
        Company, on_delete=models.CASCADE,
        null=True, blank=True, related_name='portal_logs'
    )
    employee = models.ForeignKey(
        Employee, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='portal_logs'
    )
    attendance_location = models.ForeignKey(
        AttendanceLocation, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='portal_logs'
    )
    attendance_record = models.ForeignKey(
        AttendanceRecord, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='portal_logs'
    )
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    blocked_reason = models.TextField(blank=True)
    # Placeholder GPS fields — not yet enforced
    gps_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    gps_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    gps_accuracy = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    selfie_image = models.ImageField(
        upload_to=portal_selfie_upload_path,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['company', 'created_at']),
            models.Index(fields=['employee', 'created_at']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        emp = self.employee or 'unknown'
        return f'{emp} — {self.get_action_display()} @ {self.created_at:%Y-%m-%d %H:%M} ({self.get_status_display()})'
