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
    PAY_BASIS_CHOICES = [
        ('daily', 'Daily / Payable-days'),
        ('monthly', 'Monthly (fixed salary includes holidays)'),
    ]
    OVERTIME_POLICY_CHOICES = [
        ('not_allowed',       'Not Allowed'),
        ('automatic',         'Automatic'),
        ('request_required',  'Request Required'),
        ('management_review', 'Management Review'),
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
    daily_rate = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text='Daily pay rate for daily-paid employees. Monthly employees '
                  'use basic salary; daily employees use daily rate. Leave blank '
                  'to compute from basic salary (÷ 26).',
    )
    pay_basis = models.CharField(
        max_length=10, choices=PAY_BASIS_CHOICES, default='daily',
        help_text='Daily: paid per payable day. Monthly: fixed salary already '
                  'includes paid holidays (no-work holidays are not docked).',
    )
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
    sss_contribution_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text='Fixed monthly SSS contribution to deduct from payroll.',
    )
    philhealth_contribution_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text='Fixed monthly PhilHealth contribution to deduct from payroll.',
    )
    pagibig_contribution_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text='Fixed monthly Pag-IBIG contribution to deduct from payroll.',
    )
    tax_deduction_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text='Fixed monthly withholding tax to deduct from payroll.',
    )
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
    overtime_policy = models.CharField(
        max_length=20, choices=OVERTIME_POLICY_CHOICES, default='not_allowed',
        help_text='Controls how this employee\'s overtime is paid by payroll.',
    )
    flexible_schedule_enabled = models.BooleanField(
        default=False,
        help_text='If on, attendance uses required daily hours instead of a fixed start/end.',
    )
    required_daily_hours = models.DecimalField(
        max_digits=4, decimal_places=2, default=8.00,
        help_text='Hours a flexible employee must complete per day.',
    )
    allowed_clock_in_from = models.TimeField(
        null=True, blank=True,
        help_text='Earliest allowed clock-in for flexible employees.',
    )
    allowed_clock_in_until = models.TimeField(
        null=True, blank=True,
        help_text='Latest allowed clock-in for flexible employees.',
    )
    default_break_minutes = models.PositiveIntegerField(
        default=60,
        help_text='Break minutes assumed for flexible computation when not recorded.',
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

    @property
    def effective_daily_rate(self):
        """
        Daily pay rate used for display and payroll.

        Daily-paid employees use their explicit ``daily_rate``; everyone else
        (and daily employees who left it blank) falls back to the computed
        ``basic_salary / 26``. Returns ``None`` when there is nothing to show.
        """
        from decimal import Decimal, ROUND_HALF_UP
        if self.pay_basis == 'daily' and self.daily_rate:
            return Decimal(self.daily_rate)
        salary = Decimal(self.basic_salary or 0)
        if salary <= 0:
            return None
        return (salary / Decimal('26')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
