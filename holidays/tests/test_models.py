import datetime

from django.core.exceptions import ValidationError
from django.db.utils import IntegrityError
from django.test import TestCase

from companies.models import Company
from employees.models import Department, Employee
from holidays.constants import TYPE_REGULAR, SOURCE_COMPANY
from holidays.models import CompanyHolidayPolicy, Holiday, HolidayException


def make_company(name="Acme"):
    return Company.objects.create(name=name, email=f"{name.lower()}@t.com")


class HolidayModelTests(TestCase):
    def setUp(self):
        self.company = make_company()
        # Company creation auto-seeds holidays + a policy (see holidays.signals).
        # Clear them so these tests exercise creation/uniqueness in isolation.
        Holiday.objects.filter(company=self.company).delete()
        CompanyHolidayPolicy.objects.filter(company=self.company).delete()

    def test_create_holiday_defaults(self):
        h = Holiday.objects.create(
            company=self.company, name="Christmas Day",
            date=datetime.date(2026, 12, 25), holiday_type=TYPE_REGULAR,
            source=SOURCE_COMPANY, is_paid=True,
        )
        self.assertTrue(h.is_enabled)
        self.assertEqual(str(h.no_work_pay_pct), "100.00")
        self.assertEqual(str(h.worked_multiplier), "1.00")

    def test_unique_company_date_name(self):
        kw = dict(company=self.company, name="X",
                  date=datetime.date(2026, 1, 1), holiday_type=TYPE_REGULAR)
        Holiday.objects.create(**kw)
        with self.assertRaises(IntegrityError):
            Holiday.objects.create(**kw)

    def test_policy_defaults(self):
        p = CompanyHolidayPolicy.objects.create(company=self.company)
        self.assertEqual(str(p.regular_worked_multiplier), "2.00")
        self.assertEqual(str(p.special_nonworking_worked_multiplier), "1.30")
        self.assertFalse(p.special_nonworking_default_paid)

    def test_exception_requires_exactly_one_target(self):
        h = Holiday.objects.create(
            company=self.company, name="X", date=datetime.date(2026, 1, 1),
            holiday_type=TYPE_REGULAR,
        )
        exc = HolidayException(holiday=h)  # neither department nor employee
        with self.assertRaises(ValidationError):
            exc.full_clean()


class EmployeePayBasisTests(TestCase):
    def test_default_pay_basis_is_daily(self):
        company = make_company("E")
        dept = Department.objects.create(company=company, name="Ops")
        emp = Employee.objects.create(
            company=company, employee_id="E1", first_name="A", last_name="B",
            email="a@b.com", date_hired=datetime.date(2024, 1, 1), department=dept,
        )
        self.assertEqual(emp.pay_basis, "daily")
