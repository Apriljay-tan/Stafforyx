from decimal import Decimal

from django.db import models

from companies.models import Company
from employees.models import Employee


class PayrollPeriod(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('processing', 'Processing'),
        ('approved', 'Approved'),
        ('paid', 'Paid'),
    ]
    CUTOFF_TYPE_CHOICES = [
        ('custom', 'Custom'),
        ('semi_monthly', 'Semi-Monthly'),
        ('monthly', 'Monthly'),
        ('weekly', 'Weekly'),
    ]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='payroll_periods')
    name = models.CharField(max_length=100)
    start_date = models.DateField()
    end_date = models.DateField()
    pay_date = models.DateField(null=True, blank=True)
    cutoff_type = models.CharField(
        max_length=20, choices=CUTOFF_TYPE_CHOICES, default='custom', blank=True
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-start_date']

    def __str__(self):
        return f"{self.name} ({self.company.name})"


class PayrollRecord(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('approved', 'Approved'),
        ('paid', 'Paid'),
    ]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='payroll_records')
    payroll_period = models.ForeignKey(PayrollPeriod, on_delete=models.CASCADE, related_name='records')
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='payroll_records')

    # ── Attendance breakdown (populated by V2 engine) ─────────────────────────
    scheduled_days = models.PositiveIntegerField(default=0)
    present_days = models.PositiveIntegerField(default=0)
    paid_leave_days = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    unpaid_leave_days = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    absent_days = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    payable_days = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    late_minutes = models.PositiveIntegerField(default=0)
    undertime_minutes = models.PositiveIntegerField(default=0)
    overtime_minutes = models.PositiveIntegerField(default=0)
    daily_rate = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    hourly_rate = models.DecimalField(max_digits=10, decimal_places=4, default=0)

    # ── Pay components ────────────────────────────────────────────────────────
    basic_pay = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    allowances = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    overtime_pay = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gross_pay = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # ── Deductions ────────────────────────────────────────────────────────────
    sss_deduction = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    philhealth_deduction = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    pagibig_deduction = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    tax_deduction = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    late_deduction = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    undertime_deduction = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    # absence_deduction is informational only — absent days are already excluded from basic_pay
    absence_deduction = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    # other_deductions kept for legacy/manual records; use PayrollAdjustment for new items
    other_deductions = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    net_pay = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    payslip_sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = ('payroll_period', 'employee')

    def __str__(self):
        return f"{self.employee} — {self.payroll_period.name} (Net: ₱{self.net_pay})"

    def recalculate(self):
        """
        Recompute gross_pay and net_pay from current component fields + PayrollAdjustments.
        Call after adding/removing adjustments or editing pay components.
        """
        zero = Decimal('0.00')
        earning_adj = sum(
            (a.amount for a in self.adjustments.filter(adjustment_type='earning')),
            zero,
        )
        deduction_adj = sum(
            (a.amount for a in self.adjustments.filter(adjustment_type='deduction')),
            zero,
        )
        self.gross_pay = (
            (self.basic_pay or zero) +
            (self.overtime_pay or zero) +
            (self.allowances or zero) +
            earning_adj
        ).quantize(Decimal('0.01'))
        total_ded = (
            (self.sss_deduction or zero) +
            (self.philhealth_deduction or zero) +
            (self.pagibig_deduction or zero) +
            (self.tax_deduction or zero) +
            (self.late_deduction or zero) +
            (self.undertime_deduction or zero) +
            (self.other_deductions or zero) +
            deduction_adj
        )
        self.net_pay = (self.gross_pay - total_ded).quantize(Decimal('0.01'))
        self.save(update_fields=['gross_pay', 'net_pay'])


class PayrollAdjustment(models.Model):
    """
    Itemized earning or deduction attached to a PayrollRecord.
    Examples: Cash Advance, Loan Deduction, Bonus, Rice Allowance, Damages.
    """
    TYPE_CHOICES = [
        ('earning',   'Earning'),
        ('deduction', 'Deduction'),
    ]

    payroll_record = models.ForeignKey(
        PayrollRecord, on_delete=models.CASCADE, related_name='adjustments'
    )
    name = models.CharField(max_length=100)
    adjustment_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    remarks = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['adjustment_type', 'name']

    def __str__(self):
        sign = '+' if self.adjustment_type == 'earning' else '-'
        return f"{self.name} ({sign}₱{self.amount})"
