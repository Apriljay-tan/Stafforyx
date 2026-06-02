from django.test import TestCase

from companies.models import Company
from holidays.constants import (
    SOURCE_SYSTEM_DEFAULT, TYPE_REGULAR, TYPE_SPECIAL_NON_WORKING,
)
from holidays.holiday_data import holidays_for_year
from holidays.models import CompanyHolidayPolicy, Holiday
from holidays.seeding import get_or_create_policy, seed_default_holidays


class SeedingTests(TestCase):
    def setUp(self):
        # Company creation auto-seeds (Task 4). Use update_or_create-free company
        # and clear to test seeding in isolation.
        self.company = Company.objects.create(name="Seed Co", email="s@t.com")
        Holiday.objects.filter(company=self.company).delete()

    def test_seed_creates_expected_count_and_fields(self):
        created = seed_default_holidays(self.company, 2026)
        expected = len(holidays_for_year(2026))
        self.assertEqual(created, expected)
        self.assertEqual(Holiday.objects.filter(company=self.company).count(), expected)

        labor = Holiday.objects.get(company=self.company, name="Labor Day")
        self.assertEqual(labor.holiday_type, TYPE_REGULAR)
        self.assertEqual(labor.source, SOURCE_SYSTEM_DEFAULT)
        self.assertTrue(labor.is_paid)
        self.assertEqual(str(labor.worked_multiplier), "2.00")   # from policy
        self.assertEqual(str(labor.no_work_pay_pct), "100.00")

        edsa = Holiday.objects.get(company=self.company, name="EDSA People Power Anniversary")
        self.assertEqual(edsa.holiday_type, TYPE_SPECIAL_NON_WORKING)
        self.assertFalse(edsa.is_paid)                            # default not paid
        self.assertEqual(str(edsa.worked_multiplier), "1.30")
        self.assertEqual(str(edsa.no_work_pay_pct), "0.00")

    def test_seed_is_idempotent(self):
        seed_default_holidays(self.company, 2026)
        again = seed_default_holidays(self.company, 2026)
        self.assertEqual(again, 0)
        self.assertEqual(
            Holiday.objects.filter(company=self.company).count(),
            len(holidays_for_year(2026)),
        )

    def test_get_or_create_policy(self):
        CompanyHolidayPolicy.objects.filter(company=self.company).delete()
        p1 = get_or_create_policy(self.company)
        p2 = get_or_create_policy(self.company)
        self.assertEqual(p1.pk, p2.pk)
