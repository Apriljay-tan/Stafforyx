from decimal import Decimal

from django.contrib.auth.models import User
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
    # Statuses an employee may see in the self-service portal. Draft payroll is
    # internal-only until an admin/payroll officer approves it.
    EMPLOYEE_VISIBLE_STATUSES = ('approved', 'paid')
    # Only draft payroll may be deleted — approved/paid records are financial
    # audit data and must be preserved.
    DELETABLE_STATUSES = ('draft',)

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
    overtime_multiplier = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal('1.25'))
    night_differential_minutes = models.PositiveIntegerField(default=0)
    night_differential_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    daily_rate = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    hourly_rate = models.DecimalField(max_digits=10, decimal_places=4, default=0)

    # ── Pay components ────────────────────────────────────────────────────────
    basic_pay = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    allowances = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    overtime_pay = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    night_differential_pay = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    holiday_pay = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    holiday_days = models.PositiveIntegerField(default=0)
    holiday_worked_days = models.PositiveIntegerField(default=0)
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

    def calculate_totals(self):
        """
        Return gross, deduction, and net totals from component fields plus adjustments.

        This is the single calculation source used for persisted PayrollRecord
        totals and for display. Absence deduction is intentionally excluded
        because absent days are already excluded from basic_pay.
        """
        zero = Decimal('0.00')
        earning_adj = zero
        deduction_adj = zero

        if self.pk:
            for adj in self.adjustments.all():
                amount = adj.amount or zero
                if adj.adjustment_type == 'earning':
                    earning_adj += amount
                elif adj.adjustment_type == 'deduction':
                    deduction_adj += amount

        gross_pay = (
            (self.basic_pay or zero) +
            (self.overtime_pay or zero) +
            (self.night_differential_pay or zero) +
            (self.holiday_pay or zero) +
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
        ).quantize(Decimal('0.01'))
        net_pay = (gross_pay - total_ded).quantize(Decimal('0.01'))
        return {
            'gross_pay': gross_pay,
            'total_deductions': total_ded,
            'net_pay': net_pay,
        }

    @property
    def calculated_gross_pay(self):
        return self.calculate_totals()['gross_pay']

    @property
    def calculated_total_deductions(self):
        return self.calculate_totals()['total_deductions']

    @property
    def calculated_net_pay(self):
        return self.calculate_totals()['net_pay']

    def recalculate(self):
        """
        Recompute and persist gross_pay and net_pay from current component fields
        plus PayrollAdjustments.
        """
        totals = self.calculate_totals()
        self.gross_pay = totals['gross_pay']
        self.net_pay = totals['net_pay']
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
    # Set when this deduction line was generated from a released Cash Advance
    # (Phase 6C). Lets payroll roll the CA balance forward without duplicating.
    source_cash_advance = models.ForeignKey(
        'cash_advance.CashAdvanceRequest',
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='deduction_adjustments',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['adjustment_type', 'name']

    def __str__(self):
        sign = '+' if self.adjustment_type == 'earning' else '-'
        return f"{self.name} ({sign}₱{self.amount})"

    def save(self, *args, **kwargs):
        old_record_id = None
        if self.pk:
            old_record_id = (
                PayrollAdjustment.objects
                .filter(pk=self.pk)
                .values_list('payroll_record_id', flat=True)
                .first()
            )
        super().save(*args, **kwargs)
        if old_record_id and old_record_id != self.payroll_record_id:
            try:
                PayrollRecord.objects.get(pk=old_record_id).recalculate()
            except PayrollRecord.DoesNotExist:
                pass
        if self.payroll_record_id:
            self.payroll_record.recalculate()
        # Keep the source cash advance's deduction totals/status in sync.
        if self.source_cash_advance_id:
            self.source_cash_advance.reconcile_deductions()

    def delete(self, *args, **kwargs):
        record = self.payroll_record
        source_ca = self.source_cash_advance
        result = super().delete(*args, **kwargs)
        if record.pk:
            record.recalculate()
        if source_ca is not None:
            source_ca.reconcile_deductions()
        return result


class ArchiveBatch(models.Model):
    """
    Audit record for a Payroll Archive & Cleanup operation.

    An ArchiveBatch is created when an admin exports payroll-related data for a
    company + date range to an Excel file. It records what was exported and,
    later, what was cleared. The metadata is retained even if the exported
    Excel file is deleted from disk, so the archive history stays auditable.
    """
    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name='archive_batches'
    )
    payroll_period = models.ForeignKey(
        PayrollPeriod, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='archive_batches',
    )
    date_from = models.DateField()
    date_to = models.DateField()

    file_name = models.CharField(max_length=255)
    # Path relative to MEDIA_ROOT. The metadata below is kept even if the file
    # is later removed from disk.
    file_path = models.CharField(max_length=500, blank=True)

    # Snapshot of how many records were included in the export.
    payroll_count = models.PositiveIntegerField(default=0)
    attendance_count = models.PositiveIntegerField(default=0)
    portal_log_count = models.PositiveIntegerField(default=0)
    qr_log_count = models.PositiveIntegerField(default=0)
    overtime_count = models.PositiveIntegerField(default=0)
    leave_count = models.PositiveIntegerField(default=0)
    ca_count = models.PositiveIntegerField(default=0)

    # Per-model counts actually deleted during cleanup (populated on clear).
    cleared_counts = models.JSONField(default=dict, blank=True)

    generated_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='generated_archive_batches',
    )
    generated_at = models.DateTimeField(auto_now_add=True)
    cleared_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='cleared_archive_batches',
    )
    cleared_at = models.DateTimeField(null=True, blank=True)
    is_cleared = models.BooleanField(default=False)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-generated_at']
        indexes = [
            models.Index(fields=['company', 'generated_at']),
            models.Index(fields=['is_cleared']),
        ]

    def __str__(self):
        return f'{self.company.name} archive {self.date_from}–{self.date_to}'

    @property
    def total_exported(self):
        return (
            self.payroll_count + self.attendance_count + self.portal_log_count
            + self.qr_log_count + self.overtime_count + self.leave_count
            + self.ca_count
        )

    @property
    def total_cleared(self):
        try:
            return sum(int(v) for v in (self.cleared_counts or {}).values())
        except (TypeError, ValueError):
            return 0
