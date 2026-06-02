import datetime
from decimal import Decimal

from django.test import TestCase

from companies.models import Company
from employees.models import Employee
from payroll.models import PayrollPeriod, PayrollRecord


class HolidayPayRecalculateTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="P", email="p@t.com")
        self.period = PayrollPeriod.objects.create(
            company=self.company, name="May 2026",
            start_date=datetime.date(2026, 5, 1), end_date=datetime.date(2026, 5, 15),
        )
        self.emp = Employee.objects.create(
            company=self.company, employee_id="E1", first_name="A", last_name="B",
            email="a@b.com", date_hired=datetime.date(2024, 1, 1), basic_salary=26000,
        )

    def test_holiday_pay_included_in_gross_and_net(self):
        rec = PayrollRecord.objects.create(
            company=self.company, payroll_period=self.period, employee=self.emp,
            basic_pay=Decimal("10000.00"), holiday_pay=Decimal("2000.00"),
        )
        rec.recalculate()
        rec.refresh_from_db()
        self.assertEqual(rec.gross_pay, Decimal("12000.00"))
        self.assertEqual(rec.net_pay, Decimal("12000.00"))

    def test_holiday_fields_default_zero(self):
        rec = PayrollRecord.objects.create(
            company=self.company, payroll_period=self.period, employee=self.emp)
        self.assertEqual(rec.holiday_pay, Decimal("0"))
        self.assertEqual(rec.holiday_days, 0)
        self.assertEqual(rec.holiday_worked_days, 0)
