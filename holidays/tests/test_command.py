from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from companies.models import Company
from holidays.holiday_data import holidays_for_year
from holidays.models import Holiday


class SeedHolidaysCommandTests(TestCase):
    def setUp(self):
        self.c1 = Company.objects.create(name="C1", email="c1@t.com")
        self.c2 = Company.objects.create(name="C2", email="c2@t.com")
        Holiday.objects.all().delete()  # clear auto-seeded rows

    def test_seeds_all_companies_for_year(self):
        out = StringIO()
        call_command("seed_holidays", "--year", "2026", stdout=out)
        expected = len(holidays_for_year(2026))
        self.assertEqual(Holiday.objects.filter(company=self.c1).count(), expected)
        self.assertEqual(Holiday.objects.filter(company=self.c2).count(), expected)

    def test_seeds_single_company(self):
        call_command("seed_holidays", "--company", str(self.c1.pk), "--year", "2026")
        self.assertEqual(
            Holiday.objects.filter(company=self.c1).count(), len(holidays_for_year(2026)))
        self.assertEqual(Holiday.objects.filter(company=self.c2).count(), 0)

    def test_idempotent(self):
        call_command("seed_holidays", "--year", "2026")
        call_command("seed_holidays", "--year", "2026")
        self.assertEqual(
            Holiday.objects.filter(company=self.c1).count(), len(holidays_for_year(2026)))
