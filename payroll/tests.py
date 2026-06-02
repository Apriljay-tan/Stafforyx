"""
Payroll V2 engine tests.

Uses the period May 19–23 2025 (Mon–Fri, 5 scheduled days) with a Mon–Fri WorkSchedule
and a basic_salary of 26 000 so that daily_rate = 1 000.00 exactly.

Ten scenarios:
  1. Full attendance (5/5 present)  → payable=5, basic=5000, net=5000
  2. Partial attendance (2/5 present) → payable=2, basic=2000, absent_days=3
  3. Fully absent (0/5 present)     → payable=0, basic=0, absence_deduction stored only
  4. Paid leave (1 day)             → paid_leave counted in payable days
  5. Unpaid leave (1 day)           → NOT counted in payable; absent_days stays same
  6. Late minutes deduction         → late_deduction = (min/60)*hourly_rate
  7. Overtime pay                   → overtime_pay = (min/60)*hourly_rate*1.25
  8. Undertime deduction            → undertime_deduction applied
  9. PayrollAdjustment earning      → adds to gross_pay via recalculate()
 10. PayrollAdjustment deduction    → subtracts from net_pay via recalculate()
 11. Contribution fields carried to record
 12. Approved/Paid records are skipped during regenerate
"""
import datetime
from decimal import Decimal

from django.test import TestCase

from attendance.models import AttendanceRecord, WorkSchedule
from companies.models import Company
from employees.models import Employee
from leaves.models import LeaveRequest, LeaveType
from payroll.models import PayrollAdjustment, PayrollPeriod, PayrollRecord
from payroll.services import generate_payroll_for_period
from overtime.models import OvertimeRequest


# ── Shared helpers ─────────────────────────────────────────────────────────────

_MAY_19 = datetime.date(2025, 5, 19)  # Monday
_MAY_20 = datetime.date(2025, 5, 20)  # Tuesday
_MAY_21 = datetime.date(2025, 5, 21)  # Wednesday
_MAY_22 = datetime.date(2025, 5, 22)  # Thursday
_MAY_23 = datetime.date(2025, 5, 23)  # Friday

_SALARY = Decimal('26000.00')
_DAILY  = Decimal('1000.0000')   # 26000 / 26
_HOURLY = Decimal('125.0000')    # 1000 / 8


class PayrollV2TestCase(TestCase):
    """Base class — builds company, schedule, employee, and period."""

    def setUp(self):
        self.company = Company.objects.create(
            name='Test Corp',
            email='corp@test.com',
        )
        self.schedule = WorkSchedule.objects.create(
            company=self.company,
            name='Standard',
            start_time=datetime.time(8, 0),
            end_time=datetime.time(17, 0),
            grace_minutes=15,
            work_monday=True,
            work_tuesday=True,
            work_wednesday=True,
            work_thursday=True,
            work_friday=True,
            work_saturday=False,
            work_sunday=False,
            is_active=True,
        )
        self.emp = Employee.objects.create(
            company=self.company,
            employee_id='EMP001',
            first_name='Juan',
            last_name='Dela Cruz',
            email='juan@test.com',
            date_hired=datetime.date(2020, 1, 1),
            basic_salary=_SALARY,
            work_schedule=self.schedule,
            status='active',
        )
        self.period = PayrollPeriod.objects.create(
            company=self.company,
            name='May 19-23 2025',
            start_date=_MAY_19,
            end_date=_MAY_23,
        )

    def _clock_in(self, date, late_min=0, undertime_min=0, overtime_min=0):
        AttendanceRecord.objects.create(
            company=self.company,
            employee=self.emp,
            date=date,
            time_in=datetime.time(8, 0),
            late_minutes=late_min,
            undertime_minutes=undertime_min,
            overtime_minutes=overtime_min,
        )

    def _generate(self, allow_update=True):
        return generate_payroll_for_period(self.period, allow_update_draft=allow_update)

    def _record(self):
        return PayrollRecord.objects.get(payroll_period=self.period, employee=self.emp)


# ── Test 1: Full attendance ────────────────────────────────────────────────────

class FullAttendanceTest(PayrollV2TestCase):
    """Employee clocks in all 5 scheduled days — full pay, no late/OT."""

    def test_full_pay(self):
        for d in (_MAY_19, _MAY_20, _MAY_21, _MAY_22, _MAY_23):
            self._clock_in(d)

        self._generate()
        rec = self._record()

        self.assertEqual(rec.scheduled_days, 5)
        self.assertEqual(rec.present_days, 5)
        self.assertEqual(rec.payable_days, Decimal('5'))
        self.assertEqual(rec.absent_days, Decimal('0'))
        self.assertEqual(rec.basic_pay, Decimal('5000.00'))
        self.assertEqual(rec.gross_pay, Decimal('5000.00'))
        self.assertEqual(rec.net_pay, Decimal('5000.00'))
        self.assertEqual(rec.status, 'draft')


# ── Test 2: Partial attendance ─────────────────────────────────────────────────

class PartialAttendanceTest(PayrollV2TestCase):
    """Employee only comes in 2 of 5 days — must NOT receive full pay."""

    def test_partial_pay(self):
        self._clock_in(_MAY_19)
        self._clock_in(_MAY_20)
        # Wed–Fri: no attendance records → absent

        self._generate()
        rec = self._record()

        self.assertEqual(rec.scheduled_days, 5)
        self.assertEqual(rec.present_days, 2)
        self.assertEqual(rec.absent_days, Decimal('3'))
        self.assertEqual(rec.payable_days, Decimal('2'))
        self.assertEqual(rec.basic_pay, Decimal('2000.00'))
        self.assertLess(rec.net_pay, Decimal('5000.00'))


# ── Test 3: Fully absent ───────────────────────────────────────────────────────

class FullyAbsentTest(PayrollV2TestCase):
    """Employee has no attendance at all — basic_pay=0, absence_deduction is display only."""

    def test_zero_pay_no_double_deduction(self):
        # No attendance records

        self._generate()
        rec = self._record()

        self.assertEqual(rec.scheduled_days, 5)
        self.assertEqual(rec.present_days, 0)
        self.assertEqual(rec.absent_days, Decimal('5'))
        self.assertEqual(rec.payable_days, Decimal('0'))
        self.assertEqual(rec.basic_pay, Decimal('0.00'))
        self.assertEqual(rec.gross_pay, Decimal('0.00'))
        # absence_deduction stored for display
        self.assertEqual(rec.absence_deduction, Decimal('5000.00'))
        # net_pay must NOT subtract absence_deduction again
        self.assertEqual(rec.net_pay, Decimal('0.00'))


# ── Test 4: Paid leave ─────────────────────────────────────────────────────────

class PaidLeaveTest(PayrollV2TestCase):
    """1 paid leave day counts as a payable day (no double-deduction)."""

    def setUp(self):
        super().setUp()
        self.leave_type = LeaveType.objects.create(
            company=self.company,
            name='Vacation Leave',
            is_paid=True,
        )

    def test_paid_leave_counts_as_payable(self):
        # Present Mon–Thu; paid leave on Fri
        for d in (_MAY_19, _MAY_20, _MAY_21, _MAY_22):
            self._clock_in(d)
        LeaveRequest.objects.create(
            company=self.company,
            employee=self.emp,
            leave_type=self.leave_type,
            start_date=_MAY_23,
            end_date=_MAY_23,
            total_days=1,
            reason='Vacation',
            status='approved',
        )

        self._generate()
        rec = self._record()

        self.assertEqual(rec.present_days, 4)
        self.assertEqual(rec.paid_leave_days, Decimal('1'))
        self.assertEqual(rec.absent_days, Decimal('0'))
        self.assertEqual(rec.payable_days, Decimal('5'))
        self.assertEqual(rec.basic_pay, Decimal('5000.00'))


# ── Test 5: Unpaid leave ───────────────────────────────────────────────────────

class UnpaidLeaveTest(PayrollV2TestCase):
    """Unpaid leave does NOT count as a payable day."""

    def setUp(self):
        super().setUp()
        self.leave_type = LeaveType.objects.create(
            company=self.company,
            name='Unpaid Leave',
            is_paid=False,
        )

    def test_unpaid_leave_not_payable(self):
        for d in (_MAY_19, _MAY_20, _MAY_21, _MAY_22):
            self._clock_in(d)
        LeaveRequest.objects.create(
            company=self.company,
            employee=self.emp,
            leave_type=self.leave_type,
            start_date=_MAY_23,
            end_date=_MAY_23,
            total_days=1,
            reason='No pay leave',
            status='approved',
        )

        self._generate()
        rec = self._record()

        self.assertEqual(rec.present_days, 4)
        self.assertEqual(rec.unpaid_leave_days, Decimal('1'))
        self.assertEqual(rec.paid_leave_days, Decimal('0'))
        self.assertEqual(rec.payable_days, Decimal('4'))   # only present
        self.assertEqual(rec.basic_pay, Decimal('4000.00'))
        self.assertEqual(rec.absent_days, Decimal('0'))    # unpaid leave ≠ absent


# ── Test 6: Late deduction ─────────────────────────────────────────────────────

class LateDeductionTest(PayrollV2TestCase):
    """Late minutes reduce pay at hourly_rate per minute."""

    def test_late_deduction(self):
        # 60 min late on Mon; present all 5 days
        self._clock_in(_MAY_19, late_min=60)
        for d in (_MAY_20, _MAY_21, _MAY_22, _MAY_23):
            self._clock_in(d)

        self._generate()
        rec = self._record()

        self.assertEqual(rec.late_minutes, 60)
        # late_deduction = (60/60) * 125 = 125.00
        self.assertEqual(rec.late_deduction, Decimal('125.00'))
        self.assertEqual(rec.basic_pay, Decimal('5000.00'))
        expected_net = Decimal('5000.00') - Decimal('125.00')
        self.assertEqual(rec.net_pay, expected_net)


# ── Test 7: Overtime pay ───────────────────────────────────────────────────────

class OvertimePayTest(PayrollV2TestCase):
    """Overtime minutes add pay at hourly_rate * 1.25."""

    def test_overtime_pay(self):
        # 120 min OT on Monday; present all 5 days.
        # Policy 'automatic' = detected OT is paid without a request (preserves
        # this test's original intent now that payroll gates OT by policy).
        self.emp.overtime_policy = 'automatic'
        self.emp.save(update_fields=['overtime_policy'])
        self._clock_in(_MAY_19, overtime_min=120)
        for d in (_MAY_20, _MAY_21, _MAY_22, _MAY_23):
            self._clock_in(d)

        self._generate()
        rec = self._record()

        self.assertEqual(rec.overtime_minutes, 120)
        # ot_pay = (120/60) * 125 * 1.25 = 2 * 125 * 1.25 = 312.50
        self.assertEqual(rec.overtime_pay, Decimal('312.50'))
        self.assertEqual(rec.gross_pay, Decimal('5000.00') + Decimal('312.50'))


# ── Test 8: Undertime deduction ────────────────────────────────────────────────

class UndertimeDeductionTest(PayrollV2TestCase):
    """Undertime minutes reduce pay at hourly_rate."""

    def test_undertime_deduction(self):
        self._clock_in(_MAY_19, undertime_min=30)
        for d in (_MAY_20, _MAY_21, _MAY_22, _MAY_23):
            self._clock_in(d)

        self._generate()
        rec = self._record()

        self.assertEqual(rec.undertime_minutes, 30)
        # undertime_ded = (30/60) * 125 = 62.50
        self.assertEqual(rec.undertime_deduction, Decimal('62.50'))
        expected_net = Decimal('5000.00') - Decimal('62.50')
        self.assertEqual(rec.net_pay, expected_net)


# ── Test 9: PayrollAdjustment — earning ───────────────────────────────────────

class EarningAdjustmentTest(PayrollV2TestCase):
    """An 'earning' PayrollAdjustment increases gross_pay and net_pay."""

    def test_earning_adjustment(self):
        for d in (_MAY_19, _MAY_20, _MAY_21, _MAY_22, _MAY_23):
            self._clock_in(d)
        self._generate()
        rec = self._record()

        self.assertEqual(rec.gross_pay, Decimal('5000.00'))
        self.assertEqual(rec.net_pay, Decimal('5000.00'))

        PayrollAdjustment.objects.create(
            payroll_record=rec,
            name='Performance Bonus',
            adjustment_type='earning',
            amount=Decimal('500.00'),
        )
        rec.recalculate()
        rec.refresh_from_db()

        self.assertEqual(rec.gross_pay, Decimal('5500.00'))
        self.assertEqual(rec.net_pay, Decimal('5500.00'))


# ── Test 10: PayrollAdjustment — deduction ────────────────────────────────────

class DeductionAdjustmentTest(PayrollV2TestCase):
    """A 'deduction' PayrollAdjustment reduces net_pay without touching gross_pay."""

    def test_deduction_adjustment(self):
        for d in (_MAY_19, _MAY_20, _MAY_21, _MAY_22, _MAY_23):
            self._clock_in(d)
        self._generate()
        rec = self._record()

        PayrollAdjustment.objects.create(
            payroll_record=rec,
            name='Cash Advance',
            adjustment_type='deduction',
            amount=Decimal('1000.00'),
        )
        rec.recalculate()
        rec.refresh_from_db()

        self.assertEqual(rec.gross_pay, Decimal('5000.00'))
        self.assertEqual(rec.net_pay, Decimal('4000.00'))


# ── Test 11: Contribution fields carried to record ────────────────────────────

class ContributionFieldsTest(PayrollV2TestCase):
    """SSS/PhilHealth/Pag-IBIG/tax set on Employee are copied to PayrollRecord."""

    def test_contributions_applied(self):
        self.emp.sss_contribution_amount = Decimal('400.00')
        self.emp.philhealth_contribution_amount = Decimal('200.00')
        self.emp.pagibig_contribution_amount = Decimal('100.00')
        self.emp.tax_deduction_amount = Decimal('300.00')
        self.emp.save()

        for d in (_MAY_19, _MAY_20, _MAY_21, _MAY_22, _MAY_23):
            self._clock_in(d)
        self._generate()
        rec = self._record()

        self.assertEqual(rec.sss_deduction, Decimal('400.00'))
        self.assertEqual(rec.philhealth_deduction, Decimal('200.00'))
        self.assertEqual(rec.pagibig_deduction, Decimal('100.00'))
        self.assertEqual(rec.tax_deduction, Decimal('300.00'))
        expected_net = Decimal('5000.00') - Decimal('1000.00')
        self.assertEqual(rec.net_pay, expected_net)


# ── Test 12: Regenerate skips approved/paid records ───────────────────────────

class RegenerateSkipsLockedTest(PayrollV2TestCase):
    """Approved and Paid records are never overwritten during regenerate."""

    def test_approved_record_skipped(self):
        self._clock_in(_MAY_19)  # only 1 day present
        self._generate()
        rec = self._record()
        self.assertEqual(rec.present_days, 1)

        # Approve the record
        rec.status = 'approved'
        rec.save()

        # Add more attendance — if regenerate ran it would update to 2
        self._clock_in(_MAY_20)
        created, updated, skipped = self._generate()

        rec.refresh_from_db()
        self.assertEqual(skipped, 1)
        self.assertEqual(created, 0)
        self.assertEqual(updated, 0)
        self.assertEqual(rec.present_days, 1)   # unchanged

    def test_draft_record_updated(self):
        self._clock_in(_MAY_19)
        self._generate()
        rec = self._record()
        self.assertEqual(rec.present_days, 1)

        self._clock_in(_MAY_20)
        created, updated, skipped = self._generate(allow_update=True)

        rec.refresh_from_db()
        self.assertEqual(updated, 1)
        self.assertEqual(rec.present_days, 2)


# ── Test 13: Overtime gating by policy + approval ─────────────────────────────

class PayrollOvertimeGatingTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='Pay Co')
        # Mon-Fri 8-17 schedule.
        self.schedule = WorkSchedule.objects.create(
            company=self.company, name='Std',
            start_time=datetime.time(8, 0), end_time=datetime.time(17, 0),
            grace_minutes=15, break_minutes=60, required_hours=Decimal('8.00'),
        )
        # Single-day period on a Monday.
        self.day = datetime.date(2026, 5, 25)  # Monday
        self.period = PayrollPeriod.objects.create(
            company=self.company, name='May D1',
            start_date=self.day, end_date=self.day,
        )

    def _emp(self, policy):
        emp = Employee.objects.create(
            company=self.company, employee_id=f'P-{policy}',
            first_name='Pay', last_name='Roll',
            date_hired=datetime.date(2024, 1, 1), status='active',
            basic_salary=Decimal('26000.00'),  # daily_rate=1000, hourly=125
            overtime_policy=policy,
        )
        emp.work_schedule = self.schedule
        emp.save(update_fields=['work_schedule'])
        return emp

    def _attendance(self, emp, overtime_minutes=120):
        return AttendanceRecord.objects.create(
            company=self.company, employee=emp, date=self.day,
            time_in=datetime.time(8, 0), time_out=datetime.time(19, 0),
            overtime_minutes=overtime_minutes, status='present',
        )

    def _record(self, emp):
        generate_payroll_for_period(self.period)
        return PayrollRecord.objects.get(payroll_period=self.period, employee=emp)

    def test_automatic_overtime_is_paid(self):
        emp = self._emp('automatic')
        self._attendance(emp, 120)
        rec = self._record(emp)
        self.assertEqual(rec.overtime_minutes, 120)
        # 2h * 125 * 1.25 = 312.50
        self.assertEqual(rec.overtime_pay, Decimal('312.50'))

    def test_request_required_not_paid_until_approved(self):
        emp = self._emp('request_required')
        self._attendance(emp, 120)
        rec = self._record(emp)
        self.assertEqual(rec.overtime_minutes, 0)
        self.assertEqual(rec.overtime_pay, Decimal('0.00'))

    def test_request_required_paid_after_approval(self):
        emp = self._emp('request_required')
        self._attendance(emp, 120)
        OvertimeRequest.objects.create(
            company=self.company, employee=emp, date=self.day,
            requested_hours=Decimal('2.00'), approved_hours=Decimal('2.00'),
            status='approved', source='employee',
        )
        rec = self._record(emp)
        self.assertEqual(rec.overtime_minutes, 120)
        self.assertEqual(rec.overtime_pay, Decimal('312.50'))
