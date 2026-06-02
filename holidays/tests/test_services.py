import datetime
from decimal import Decimal

from django.test import TestCase

from companies.models import Company
from employees.models import Department, Employee
from holidays.constants import (
    TYPE_REGULAR, TYPE_SPECIAL_NON_WORKING, TYPE_LOCAL, SOURCE_COMPANY,
)
from holidays.models import Holiday, HolidayException
from holidays.services import (
    build_exception_index, build_holiday_index, resolve_holiday,
)

D = datetime.date


def emp(company, dept=None, eid="E1"):
    return Employee.objects.create(
        company=company, employee_id=eid, first_name="A", last_name="B",
        email=f"{eid}@b.com", date_hired=D(2024, 1, 1), department=dept,
    )


class ResolveHolidayTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="R", email="r@t.com")
        Holiday.objects.filter(company=self.company).delete()
        self.dept = Department.objects.create(company=self.company, name="Ops")
        self.e = emp(self.company, self.dept)

    def _resolve(self, date):
        hidx = build_holiday_index(self.company, date, date)
        eidx = build_exception_index(self.company)
        return resolve_holiday(self.company, self.e, date, hidx, eidx)

    def test_no_holiday_returns_none(self):
        self.assertIsNone(self._resolve(D(2026, 3, 3)))

    def test_disabled_holiday_returns_none(self):
        Holiday.objects.create(company=self.company, name="X", date=D(2026, 3, 3),
                               holiday_type=TYPE_REGULAR, is_enabled=False)
        self.assertIsNone(self._resolve(D(2026, 3, 3)))

    def test_regular_holiday_resolves_paid(self):
        Holiday.objects.create(company=self.company, name="Reg", date=D(2026, 5, 1),
                               holiday_type=TYPE_REGULAR, is_paid=True,
                               no_work_pay_pct=100, worked_multiplier=2)
        r = self._resolve(D(2026, 5, 1))
        self.assertTrue(r["is_paid"])
        self.assertEqual(str(r["worked_multiplier"]), "2.00")

    def test_priority_regular_over_local_on_same_date(self):
        Holiday.objects.create(company=self.company, name="Local", date=D(2026, 5, 1),
                               holiday_type=TYPE_LOCAL, worked_multiplier=1)
        Holiday.objects.create(company=self.company, name="Reg", date=D(2026, 5, 1),
                               holiday_type=TYPE_REGULAR, worked_multiplier=2)
        r = self._resolve(D(2026, 5, 1))
        self.assertEqual(r["holiday"].holiday_type, TYPE_REGULAR)

    def test_employee_exception_not_observed(self):
        h = Holiday.objects.create(company=self.company, name="Reg", date=D(2026, 5, 1),
                                   holiday_type=TYPE_REGULAR)
        HolidayException.objects.create(holiday=h, employee=self.e, not_observed=True)
        self.assertIsNone(self._resolve(D(2026, 5, 1)))

    def test_department_exception_overrides_pay(self):
        h = Holiday.objects.create(company=self.company, name="SNW", date=D(2026, 2, 25),
                                   holiday_type=TYPE_SPECIAL_NON_WORKING, is_paid=False,
                                   worked_multiplier=Decimal("1.30"))
        HolidayException.objects.create(holiday=h, department=self.dept,
                                        is_paid_override=True, no_work_pay_pct_override=100)
        r = self._resolve(D(2026, 2, 25))
        self.assertTrue(r["is_paid"])
        self.assertEqual(str(r["no_work_pay_pct"]), "100.00")

    def test_employee_exception_beats_department(self):
        h = Holiday.objects.create(company=self.company, name="SNW", date=D(2026, 2, 25),
                                   holiday_type=TYPE_SPECIAL_NON_WORKING, is_paid=False)
        HolidayException.objects.create(holiday=h, department=self.dept, is_paid_override=True)
        HolidayException.objects.create(holiday=h, employee=self.e, not_observed=True)
        self.assertIsNone(self._resolve(D(2026, 2, 25)))
