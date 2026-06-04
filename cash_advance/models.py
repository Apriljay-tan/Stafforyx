from decimal import Decimal

from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.db import models

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
