import datetime

from django.test import TestCase

from companies.models import Company
from holidays.holiday_data import holidays_for_year
from holidays.models import CompanyHolidayPolicy, Holiday


class AutoSeedSignalTests(TestCase):
    def test_creating_company_seeds_current_year_and_policy(self):
        # The seeding signal uses datetime.date.today().year; today is 2026.
        company = Company.objects.create(name="Signal Co", email="sig@t.com")
        year = datetime.date.today().year
        expected = len(holidays_for_year(year))
        self.assertEqual(Holiday.objects.filter(company=company).count(), expected)
        self.assertTrue(CompanyHolidayPolicy.objects.filter(company=company).exists())

    def test_signal_is_safe_on_update(self):
        company = Company.objects.create(name="Up Co", email="up@t.com")
        before = Holiday.objects.filter(company=company).count()
        company.name = "Up Co 2"
        company.save()
        self.assertEqual(Holiday.objects.filter(company=company).count(), before)
