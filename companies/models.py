from django.core.validators import MinValueValidator
from django.db import models


class Company(models.Model):
    STATUS_CHOICES = [
        ('trial', 'Trial'),
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('suspended', 'Suspended'),
    ]
    PLAN_CHOICES = [
        ('free', 'Free'),
        ('starter', 'Starter'),
        ('professional', 'Professional'),
        ('enterprise', 'Enterprise'),
    ]
    PAYSLIP_STYLE_CHOICES = [
        ('classic_excel', 'Classic Excel'),
        ('modern', 'Modern'),
    ]

    name = models.CharField(max_length=255)
    email = models.EmailField()
    phone = models.CharField(max_length=30, blank=True)
    address = models.TextField(blank=True)
    logo = models.ImageField(upload_to='companies/logos/', blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='trial')
    subscription_plan = models.CharField(max_length=20, choices=PLAN_CHOICES, default='free')

    # ── Payslip settings ─────────────────────────────────────────────────────
    payslip_company_display_name = models.CharField(
        max_length=200, blank=True,
        help_text='Override company name shown on payslips. Leave blank to use company name.',
    )
    payslip_company_address = models.TextField(
        blank=True,
        help_text='Override address shown on payslips. Leave blank to use company address.',
    )
    payslip_template_style = models.CharField(
        max_length=30, choices=PAYSLIP_STYLE_CHOICES, default='classic_excel',
    )
    payslip_accent_color = models.CharField(
        max_length=7, default='#1565C0',
        help_text='Hex color for payslip accent elements (e.g. #1565C0).',
    )
    payslip_show_company_logo = models.BooleanField(default=True)
    payslip_show_rates = models.BooleanField(
        default=True,
        help_text='Show daily rate, hourly rate, and overtime rates section.',
    )
    payslip_show_attendance_summary = models.BooleanField(default=True)
    payslip_show_overtime_breakdown = models.BooleanField(default=True)
    payslip_show_received_by = models.BooleanField(
        default=True, help_text='Show "Received by" signature line.',
    )
    payslip_footer_note = models.TextField(
        blank=True, help_text='Optional note printed at the bottom of every payslip.',
    )
    attendance_selfie_retention_days = models.PositiveIntegerField(
        default=30,
        validators=[MinValueValidator(1)],
        help_text=(
            'Attendance selfie photos older than this number of days can be deleted by the '
            'cleanup command. Attendance logs remain, but image files are removed.'
        ),
    )
    attendance_portal_log_retention_days = models.PositiveIntegerField(
        default=30,
        validators=[MinValueValidator(1)],
        help_text='Delete attendance portal logs older than this number of days during log cleanup.',
    )
    attendance_log_page_opened_events = models.BooleanField(
        default=False,
        help_text='Log each portal page visit/open event.',
    )
    attendance_log_blocked_attempts = models.BooleanField(
        default=True,
        help_text='Log blocked clock attempts (network, schedule, selfie/GPS requirement failures).',
    )
    attendance_log_clock_actions = models.BooleanField(
        default=True,
        help_text='Log time in/time out attempts and outcomes.',
    )
    attendance_auto_delete_portal_logs = models.BooleanField(
        default=True,
        help_text='Allow automatic cleanup command to delete old attendance portal logs.',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'Companies'
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def payslip_display_name(self):
        return self.payslip_company_display_name or self.name

    @property
    def payslip_display_address(self):
        return self.payslip_company_address or self.address
