from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models

from companies.models import Company
from employees.models import Department, Employee

from .constants import HOLIDAY_TYPE_CHOICES, SOURCE_CHOICES, SOURCE_COMPANY


class Holiday(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="holidays")
    name = models.CharField(max_length=150)
    date = models.DateField()
    holiday_type = models.CharField(max_length=30, choices=HOLIDAY_TYPE_CHOICES)
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default=SOURCE_COMPANY)
    is_enabled = models.BooleanField(default=True)
    is_paid = models.BooleanField(default=True)
    no_work_pay_pct = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("100.00"))
    worked_multiplier = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("1.00"))
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["date", "name"]
        unique_together = ("company", "date", "name")

    def __str__(self):
        return f"{self.name} ({self.date}) — {self.company.name}"


class HolidayException(models.Model):
    holiday = models.ForeignKey(Holiday, on_delete=models.CASCADE, related_name="exceptions")
    department = models.ForeignKey(
        Department, on_delete=models.CASCADE, null=True, blank=True,
        related_name="holiday_exceptions",
    )
    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, null=True, blank=True,
        related_name="holiday_exceptions",
    )
    not_observed = models.BooleanField(default=False)
    is_paid_override = models.BooleanField(null=True, blank=True)
    no_work_pay_pct_override = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True)
    worked_multiplier_override = models.DecimalField(
        max_digits=4, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["holiday", "department", "employee"]

    def clean(self):
        targets = [self.department_id, self.employee_id]
        set_count = sum(1 for t in targets if t)
        if set_count != 1:
            raise ValidationError(
                "Set exactly one target: either a department or an employee."
            )

    def __str__(self):
        target = self.employee or self.department
        return f"Exception: {self.holiday.name} → {target}"


class CompanyHolidayPolicy(models.Model):
    company = models.OneToOneField(
        Company, on_delete=models.CASCADE, related_name="holiday_policy")
    regular_no_work_pay_pct = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("100.00"))
    regular_worked_multiplier = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("2.00"))
    special_nonworking_default_paid = models.BooleanField(default=False)
    special_nonworking_no_work_pay_pct = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0.00"))
    special_nonworking_worked_multiplier = models.DecimalField(
        max_digits=4, decimal_places=2, default=Decimal("1.30"))
    special_working_worked_multiplier = models.DecimalField(
        max_digits=4, decimal_places=2, default=Decimal("1.00"))
    company_local_default_paid = models.BooleanField(default=True)
    company_local_worked_multiplier = models.DecimalField(
        max_digits=4, decimal_places=2, default=Decimal("1.00"))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Company holiday policies"

    def __str__(self):
        return f"Holiday Policy — {self.company.name}"
