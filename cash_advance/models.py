from decimal import Decimal

from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from companies.models import Company
from employees.models import Employee


class CashAdvanceRequest(models.Model):
    """Employee cash-advance (CA) request.

    Phase 6A/6B foundation. Payroll deduction is intentionally NOT wired up
    yet — only the request → review → release lifecycle is implemented.
    """

    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_RELEASED = 'released'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_APPROVED, 'Approved'),
        (STATUS_REJECTED, 'Rejected'),
        (STATUS_RELEASED, 'Released'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]
    # Statuses an employee is still allowed to edit/cancel their own request in.
    EMPLOYEE_EDITABLE_STATUSES = {STATUS_PENDING}

    # ── Deduction lifecycle (Phase 6C) ────────────────────────────────────────
    # Tracks how much of a *released* CA has been pulled into payroll. Kept
    # separate from ``status`` so the request approval/release flow is untouched.
    DEDUCTION_RELEASED = 'released'                 # eligible, nothing scheduled yet
    DEDUCTION_SCHEDULED = 'scheduled_for_deduction'  # line(s) on draft payroll only
    DEDUCTION_PARTIAL = 'partially_deducted'         # finalized payroll covered part
    DEDUCTION_DEDUCTED = 'deducted'                  # fully covered / paid off
    DEDUCTION_STATUS_CHOICES = [
        (DEDUCTION_RELEASED, 'Released'),
        (DEDUCTION_SCHEDULED, 'Scheduled for Deduction'),
        (DEDUCTION_PARTIAL, 'Partially Deducted'),
        (DEDUCTION_DEDUCTED, 'Deducted / Paid Off'),
    ]
    _FINALIZED_PAYROLL_STATUSES = ('approved', 'paid')

    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name='cash_advance_requests'
    )
    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name='cash_advance_requests'
    )
    amount = models.DecimalField(
        max_digits=12, decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
    )
    reason = models.TextField(blank=True)
    requested_release_date = models.DateField(
        null=True, blank=True,
        help_text='Optional date the employee would like the cash advance released.',
    )
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_PENDING)

    approved_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='approved_cash_advances',
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='rejected_cash_advances',
    )
    rejected_at = models.DateTimeField(null=True, blank=True)
    released_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='released_cash_advances',
    )
    released_at = models.DateTimeField(null=True, blank=True)
    release_note = models.TextField(blank=True)
    cancel_reason = models.TextField(blank=True)

    manager_note = models.TextField(blank=True)

    # ── Deduction tracking (Phase 6C) ─────────────────────────────────────────
    total_deducted_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00'),
        help_text='Sum of payroll deduction lines applied to this cash advance.',
    )
    deduction_status = models.CharField(
        max_length=30, choices=DEDUCTION_STATUS_CHOICES, default=DEDUCTION_RELEASED,
        help_text='How far this released cash advance has been deducted via payroll.',
    )
    deduction_started_at = models.DateTimeField(null=True, blank=True)
    fully_deducted_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['company', 'status']),
            models.Index(fields=['employee', 'status']),
        ]

    def __str__(self):
        return f'{self.employee} — {self.amount} ({self.get_status_display()})'

    @property
    def is_editable_by_employee(self):
        """Employees may only edit/cancel a request while it is still pending."""
        return self.status in self.EMPLOYEE_EDITABLE_STATUSES

    @property
    def remaining_balance(self):
        """Cash advance amount not yet covered by payroll deduction lines."""
        remaining = (self.amount or Decimal('0.00')) - (self.total_deducted_amount or Decimal('0.00'))
        return remaining if remaining > 0 else Decimal('0.00')

    @property
    def is_eligible_for_deduction(self):
        """Only *released* requests with an outstanding balance may be deducted.

        Approved-but-not-released cash advances are never deducted.
        """
        return (
            self.status == self.STATUS_RELEASED
            and self.deduction_status != self.DEDUCTION_DEDUCTED
            and self.remaining_balance > 0
        )

    def reconcile_deductions(self):
        """Recompute deduction totals/status from the linked payroll lines.

        Called whenever a linked ``PayrollAdjustment`` is created, edited, or
        removed. Recomputing from source keeps the figures correct even when a
        draft deduction is deferred/revoked or a draft payroll is regenerated.
        """
        lines = list(self.deduction_adjustments.select_related('payroll_record').all())
        total = sum((line.amount or Decimal('0.00') for line in lines), Decimal('0.00'))
        total = total.quantize(Decimal('0.01'))
        finalized = any(
            line.payroll_record.status in self._FINALIZED_PAYROLL_STATUSES
            for line in lines
        )
        now = timezone.now()

        if total <= 0:
            self.deduction_status = self.DEDUCTION_RELEASED
            self.deduction_started_at = None
            self.fully_deducted_at = None
        elif total >= (self.amount or Decimal('0.00')):
            self.deduction_status = self.DEDUCTION_DEDUCTED
            if self.deduction_started_at is None:
                self.deduction_started_at = now
            if self.fully_deducted_at is None:
                self.fully_deducted_at = now
        else:
            self.deduction_status = (
                self.DEDUCTION_PARTIAL if finalized else self.DEDUCTION_SCHEDULED
            )
            if self.deduction_started_at is None:
                self.deduction_started_at = now
            self.fully_deducted_at = None

        self.total_deducted_amount = total
        self.save(update_fields=[
            'total_deducted_amount', 'deduction_status',
            'deduction_started_at', 'fully_deducted_at', 'updated_at',
        ])
