import datetime

from django.test import SimpleTestCase

from holidays.constants import (
    TYPE_REGULAR, TYPE_SPECIAL_NON_WORKING, HOLIDAY_TYPE_VALUES,
)
from holidays.holiday_data import holidays_for_year


class HolidayDataTests(SimpleTestCase):
    def test_2026_set_present_and_well_formed(self):
        entries = holidays_for_year(2026)
        self.assertTrue(entries, "2026 holidays should be defined")
        names = {e["name"] for e in entries}
        self.assertIn("New Year's Day", names)
        self.assertIn("Labor Day", names)
        self.assertIn("Christmas Day", names)
        for e in entries:
            self.assertEqual(e["date"].year, 2026)
            self.assertIn(e["type"], HOLIDAY_TYPE_VALUES)

    def test_labor_day_is_regular_may_1(self):
        entries = {e["name"]: e for e in holidays_for_year(2026)}
        labor = entries["Labor Day"]
        self.assertEqual(labor["date"], datetime.date(2026, 5, 1))
        self.assertEqual(labor["type"], TYPE_REGULAR)

    def test_unknown_year_returns_empty(self):
        self.assertEqual(holidays_for_year(1900), [])
