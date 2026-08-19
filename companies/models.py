from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


# ── Overtime counting / rounding rule ────────────────────────────────────────
# Values are the block size in minutes ('exact' = no rounding). Counting always
# floors DOWN to the last completed block (e.g. 59 min under the 30 rule = 30).
OVERTIME_COUNTING_RULE_EXACT = 'exact'
OVERTIME_COUNTING_RULE_CHOICES = [
    (OVERTIME_COUNTING_RULE_EXACT, 'Exact minutes (no rounding)'),
    ('30', '30-minute blocks'),
    ('60', '1-hour blocks'),
    ('120', '2-hour blocks'),
]
# Employee-level choices add a blank "inherit from company" option.
EMPLOYEE_OVERTIME_COUNTING_RULE_CHOICES = (
    [('', 'Inherit from company default')] + OVERTIME_COUNTING_RULE_CHOICES
)


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
    payslip_prepared_by_name = models.CharField(
        max_length=150, blank=True,
        help_text='Name auto-filled into the "Prepared By" area of every payslip.',
    )
    payslip_prepared_by_title = models.CharField(
        max_length=100, blank=True, default='HR/Payroll Officer',
        help_text='Title shown under the preparer name (e.g. HR/Payroll Officer).',
    )
    payslip_prepared_by_signature = models.ImageField(
        upload_to='companies/signatures/', blank=True, null=True,
        help_text='Uploaded or drawn signature shown above the Prepared By line.',
    )
    payslip_footer_note = models.TextField(
        blank=True, help_text='Optional note printed at the bottom of every payslip.',
    )
    employee_chat_enabled = models.BooleanField(
        default=False,
        help_text='Master switch: allow employee portal chat for this company.',
    )
    chat_support_display_name = models.CharField(
        max_length=100,
        blank=True,
        default='',
        help_text='Persona name shown to employees in admin support chats. Blank uses global default.',
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
    attendance_ip_validation_enabled = models.BooleanField(
        default=True,
        help_text=(
            'Require employees to connect from a registered IP/network to clock in/out. '
            'Disable only if your public IP changes frequently (e.g. dynamic router). '
            'GPS and selfie requirements still apply when disabled.'
        ),
    )
    require_attendance_gps_when_ip_disabled = models.BooleanField(
        default=True,
        help_text='When IP validation is disabled, require GPS from employees before clocking.',
    )
    require_attendance_selfie_when_ip_disabled = models.BooleanField(
        default=True,
        help_text='When IP validation is disabled, require a selfie from employees before clocking.',
    )
    default_overtime_multiplier = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=Decimal('1.25'),
        verbose_name='Default overtime multiplier',
        validators=[MinValueValidator(Decimal('1.0')), MaxValueValidator(Decimal('5.0'))],
        help_text=(
            'Ordinary-day overtime rate applied to employees without their own '
            'override (1.25 = 125%). Holiday and night-differential rates are '
            'configured separately.'
        ),
    )
    default_overtime_counting_rule = models.CharField(
        max_length=10,
        choices=OVERTIME_COUNTING_RULE_CHOICES,
        default=OVERTIME_COUNTING_RULE_EXACT,
        verbose_name='Default overtime counting rule',
        help_text=(
            'How detected overtime is counted for pay. Exact = pay every minute. '
            'Block rules floor DOWN to the last completed block (e.g. under the '
            '30-minute rule, 59 min of OT counts as 30 min). Useful for flexible '
            'employees who accumulate many small overtime minutes.'
        ),
    )
    attendance_qr_validation_enabled = models.BooleanField(
        default=False,
        verbose_name='Require rotating QR code for attendance',
        help_text=(
            'Require employees to scan a live branch QR code before clocking in/out. '
            'This validates physical presence at an approved attendance location.'
        ),
    )
    attendance_qr_token_lifetime_seconds = models.PositiveIntegerField(
        default=60,
        verbose_name='QR token lifetime seconds',
        validators=[MinValueValidator(30), MaxValueValidator(300)],
        help_text='How long each rotating QR code remains valid before it refreshes.',
    )
    attendance_qr_token_retention_days = models.PositiveIntegerField(
        default=1,
        verbose_name='QR token retention days',
        validators=[MinValueValidator(1)],
        help_text=(
            'Expired QR tokens older than this can be deleted safely. '
            'This does not delete attendance records.'
        ),
    )
    attendance_auto_delete_qr_tokens = models.BooleanField(
        default=True,
        verbose_name='Auto delete expired QR tokens',
        help_text='Allows cleanup command to remove expired QR token records.',
    )
    attendance_qr_scan_log_retention_days = models.PositiveIntegerField(
        default=90,
        verbose_name='QR scan log retention days',
        validators=[MinValueValidator(1)],
        help_text='How long QR scan audit logs are kept.',
    )
    attendance_auto_delete_qr_scan_logs = models.BooleanField(
        default=False,
        verbose_name='Auto delete old QR scan logs',
        help_text=(
            'Allows cleanup command to remove old QR scan audit log records. '
            'QR scan logs are audit records, so keep this disabled if your policy requires review.'
        ),
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
