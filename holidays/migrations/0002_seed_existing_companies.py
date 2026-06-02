import datetime

from django.db import migrations

from holidays.constants import (
    SOURCE_SYSTEM_DEFAULT, TYPE_REGULAR, TYPE_SPECIAL_NON_WORKING,
    TYPE_SPECIAL_WORKING,
)
from holidays.holiday_data import holidays_for_year


def _pay_fields(policy, htype):
    if htype == TYPE_REGULAR:
        return True, policy.regular_no_work_pay_pct, policy.regular_worked_multiplier
    if htype == TYPE_SPECIAL_NON_WORKING:
        return (policy.special_nonworking_default_paid,
                policy.special_nonworking_no_work_pay_pct,
                policy.special_nonworking_worked_multiplier)
    if htype == TYPE_SPECIAL_WORKING:
        return True, 100, policy.special_working_worked_multiplier
    return (policy.company_local_default_paid,
            100 if policy.company_local_default_paid else 0,
            policy.company_local_worked_multiplier)


def backfill(apps, schema_editor):
    Company = apps.get_model("companies", "Company")
    Holiday = apps.get_model("holidays", "Holiday")
    Policy = apps.get_model("holidays", "CompanyHolidayPolicy")
    year = datetime.date.today().year
    for company in Company.objects.all():
        policy, _ = Policy.objects.get_or_create(company=company)
        for entry in holidays_for_year(year):
            is_paid, no_work_pct, worked_mult = _pay_fields(policy, entry["type"])
            Holiday.objects.get_or_create(
                company=company, date=entry["date"], name=entry["name"],
                defaults=dict(
                    holiday_type=entry["type"], source=SOURCE_SYSTEM_DEFAULT,
                    is_enabled=True, is_paid=is_paid,
                    no_work_pay_pct=no_work_pct, worked_multiplier=worked_mult,
                ),
            )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [("holidays", "0001_initial")]
    operations = [migrations.RunPython(backfill, noop)]
