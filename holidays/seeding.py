"""Seed default holidays and policy for a company. Idempotent."""
from .constants import (
    SOURCE_SYSTEM_DEFAULT, TYPE_REGULAR, TYPE_SPECIAL_NON_WORKING,
    TYPE_SPECIAL_WORKING,
)
from .holiday_data import holidays_for_year
from .models import CompanyHolidayPolicy, Holiday


def get_or_create_policy(company):
    policy, _ = CompanyHolidayPolicy.objects.get_or_create(company=company)
    return policy


def _pay_fields_for_type(policy, holiday_type):
    """Return (is_paid, no_work_pay_pct, worked_multiplier) for a type from policy."""
    if holiday_type == TYPE_REGULAR:
        return True, policy.regular_no_work_pay_pct, policy.regular_worked_multiplier
    if holiday_type == TYPE_SPECIAL_NON_WORKING:
        return (
            policy.special_nonworking_default_paid,
            policy.special_nonworking_no_work_pay_pct,
            policy.special_nonworking_worked_multiplier,
        )
    if holiday_type == TYPE_SPECIAL_WORKING:
        return True, 100, policy.special_working_worked_multiplier
    # company / local
    return (
        policy.company_local_default_paid,
        100 if policy.company_local_default_paid else 0,
        policy.company_local_worked_multiplier,
    )


def seed_default_holidays(company, year):
    """Create system-default Holiday rows for `company` and `year`. Returns count created."""
    policy = get_or_create_policy(company)
    created = 0
    for entry in holidays_for_year(year):
        is_paid, no_work_pct, worked_mult = _pay_fields_for_type(policy, entry["type"])
        _, was_created = Holiday.objects.get_or_create(
            company=company, date=entry["date"], name=entry["name"],
            defaults=dict(
                holiday_type=entry["type"],
                source=SOURCE_SYSTEM_DEFAULT,
                is_enabled=True,
                is_paid=is_paid,
                no_work_pay_pct=no_work_pct,
                worked_multiplier=worked_mult,
            ),
        )
        if was_created:
            created += 1
    return created
