import datetime
from decimal import Decimal

from django.test import TestCase

from attendance.models import AttendanceRecord, WorkSchedule
from companies.models import Company
from employees.models import Employee
from holidays.models import Holiday
from holidays.constants import TYPE_REGULAR, TYPE_SPECIAL_NON_WORKING, SOURCE_COMPANY
from payroll.models import PayrollPeriod, PayrollRecord
from payroll.services import generate_payroll_for_period

D = datetime.date


def all_days_schedule(company):
    return WorkSchedule.objects.create(
        company=company, name="All Days", is_active=True,
        work_monday=True, work_tuesday=True, work_wednesday=True,
        work_thursday=True, work_friday=True, work_saturday=True, work_sunday=True,
        start_time=datetime.time(8, 0), end_time=datetime.time(17, 0),
    )


class HolidayEngineTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="HE", email="he@t.com")
        # Remove auto-seeded holidays so each test controls its own.
        Holiday.objects.filter(company=self.company).delete()
        self.ws = all_days_schedule(self.company)
        # Single-day period on a holiday date for precise assertions.
        self.period = PayrollPeriod.objects.create(
            company=self.company, name="Day", start_date=D(2026, 5, 1),
            end_date=D(2026, 5, 1))

    def _emp(self, pay_basis="daily", eid="E1"):
        return Employee.objects.create(
            company=self.company, employee_id=eid, first_name="A", last_name="B",
            email=f"{eid}@b.com", date_hired=D(2024, 1, 1), basic_salary=26000,
            work_schedule=self.ws, pay_basis=pay_basis,
        )

    def _record(self, emp):
        generate_payroll_for_period(self.period)
        return PayrollRecord.objects.get(payroll_period=self.period, employee=emp)

    def _reg_holiday(self, worked_mult=2, paid=True, pct=100):
        return Holiday.objects.create(
            company=self.company, name="Reg", date=D(2026, 5, 1),
            holiday_type=TYPE_REGULAR, source=SOURCE_COMPANY,
            is_paid=paid, no_work_pay_pct=pct, worked_multiplier=worked_mult)

    # daily_rate = 26000/26 = 1000.00

    def test_daily_regular_no_work_pays_one_day(self):
        emp = self._emp()
        self._reg_holiday()
        rec = self._record(emp)
        self.assertEqual(rec.holiday_pay, Decimal("1000.00"))
        self.assertEqual(rec.present_days, 0)
        self.assertEqual(rec.absent_days, Decimal("0"))   # holiday, not absence
        self.assertEqual(rec.basic_pay, Decimal("0.00"))
        self.assertEqual(rec.gross_pay, Decimal("1000.00"))
        self.assertEqual(rec.holiday_days, 1)
        self.assertEqual(rec.holiday_worked_days, 0)

    def test_daily_regular_worked_pays_double_no_double_base(self):
        emp = self._emp()
        self._reg_holiday(worked_mult=2)
        AttendanceRecord.objects.create(
            company=self.company, employee=emp, date=D(2026, 5, 1),
            time_in=datetime.time(8, 0), status="present", source="portal")
        rec = self._record(emp)
        self.assertEqual(rec.holiday_pay, Decimal("2000.00"))
        self.assertEqual(rec.present_days, 0)        # excluded from normal present
        self.assertEqual(rec.basic_pay, Decimal("0.00"))
        self.assertEqual(rec.gross_pay, Decimal("2000.00"))
        self.assertEqual(rec.holiday_worked_days, 1)

    def test_daily_special_nonworking_no_work_unpaid_by_default(self):
        emp = self._emp()
        Holiday.objects.create(
            company=self.company, name="SNW", date=D(2026, 5, 1),
            holiday_type=TYPE_SPECIAL_NON_WORKING, is_paid=False,
            no_work_pay_pct=0, worked_multiplier=Decimal("1.30"))
        rec = self._record(emp)
        self.assertEqual(rec.holiday_pay, Decimal("0.00"))
        self.assertEqual(rec.gross_pay, Decimal("0.00"))
        self.assertEqual(rec.absent_days, Decimal("0"))   # not counted as absent

    def test_daily_special_nonworking_worked_130(self):
        emp = self._emp()
        Holiday.objects.create(
            company=self.company, name="SNW", date=D(2026, 5, 1),
            holiday_type=TYPE_SPECIAL_NON_WORKING, is_paid=False,
            no_work_pay_pct=0, worked_multiplier=Decimal("1.30"))
        AttendanceRecord.objects.create(
            company=self.company, employee=emp, date=D(2026, 5, 1),
            time_in=datetime.time(8, 0), status="present", source="portal")
        rec = self._record(emp)
        self.assertEqual(rec.holiday_pay, Decimal("1300.00"))

    def test_monthly_special_nonworking_no_work_is_paid(self):
        emp = self._emp(pay_basis="monthly")
        Holiday.objects.create(
            company=self.company, name="SNW", date=D(2026, 5, 1),
            holiday_type=TYPE_SPECIAL_NON_WORKING, is_paid=False,
            no_work_pay_pct=100, worked_multiplier=Decimal("1.30"))
        rec = self._record(emp)
        # monthly basis: not docked -> paid full day even though default unpaid
        self.assertEqual(rec.holiday_pay, Decimal("1000.00"))

    def test_monthly_regular_worked_pays_double_once(self):
        emp = self._emp(pay_basis="monthly")
        self._reg_holiday(worked_mult=2)
        AttendanceRecord.objects.create(
            company=self.company, employee=emp, date=D(2026, 5, 1),
            time_in=datetime.time(8, 0), status="present", source="portal")
        rec = self._record(emp)
        self.assertEqual(rec.holiday_pay, Decimal("2000.00"))
        self.assertEqual(rec.basic_pay, Decimal("0.00"))
        self.assertEqual(rec.gross_pay, Decimal("2000.00"))
