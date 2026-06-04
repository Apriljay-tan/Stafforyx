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

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from attendance.models import AttendanceRecord, WorkSchedule
from attendance.services import compute_attendance
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


# ── Daily-rate vs monthly basic salary ──────────────────────────────────────────

class DailyRateTest(PayrollV2TestCase):
    """
    Daily-paid employees use their explicit daily_rate; monthly employees keep
    the basic_salary / 26 behaviour (daily_rate ignored).
    """

    def test_daily_employee_uses_daily_rate(self):
        self.emp.pay_basis = 'daily'
        self.emp.daily_rate = Decimal('600.00')
        self.emp.save(update_fields=['pay_basis', 'daily_rate'])
        for d in (_MAY_19, _MAY_20, _MAY_21, _MAY_22, _MAY_23):
            self._clock_in(d)

        self._generate()
        rec = self._record()
        self.assertEqual(rec.daily_rate, Decimal('600.0000'))
        self.assertEqual(rec.present_days, 5)
        self.assertEqual(rec.basic_pay, Decimal('3000.00'))   # 600 × 5

    def test_monthly_employee_ignores_daily_rate(self):
        self.emp.pay_basis = 'monthly'
        self.emp.daily_rate = Decimal('600.00')   # must be ignored for monthly
        self.emp.save(update_fields=['pay_basis', 'daily_rate'])
        for d in (_MAY_19, _MAY_20, _MAY_21, _MAY_22, _MAY_23):
            self._clock_in(d)

        self._generate()
        rec = self._record()
        self.assertEqual(rec.daily_rate, _DAILY)               # 26000 / 26 = 1000
        self.assertEqual(rec.basic_pay, Decimal('5000.00'))

    def test_daily_employee_blank_rate_falls_back_to_basic(self):
        self.emp.pay_basis = 'daily'
        self.emp.daily_rate = None
        self.emp.save(update_fields=['pay_basis', 'daily_rate'])
        for d in (_MAY_19, _MAY_20, _MAY_21, _MAY_22, _MAY_23):
            self._clock_in(d)

        self._generate()
        rec = self._record()
        self.assertEqual(rec.daily_rate, _DAILY)               # falls back to 26000 / 26


# ── Attendance status is respected (manual present / half day / on leave) ───────

class AttendanceStatusTest(PayrollV2TestCase):
    """
    Payroll must honour the AttendanceRecord.status field, not just time_in.
    A record manually marked 'present' (no clock-in) still counts; 'half_day'
    pays 0.5; explicit 'absent' is docked; 'on_leave' is neither paid nor docked.
    """

    def _record_with(self, date, status, time_in=None):
        AttendanceRecord.objects.create(
            company=self.company, employee=self.emp, date=date,
            status=status, time_in=time_in,
        )

    def test_manual_present_without_clock_in_counts(self):
        # Mon marked Present but with no time_in — must NOT be treated as absent.
        self._record_with(_MAY_19, 'present')
        self._generate()
        rec = self._record()
        self.assertEqual(rec.present_days, 1)
        self.assertEqual(rec.payable_days, Decimal('1'))
        self.assertEqual(rec.absent_days, Decimal('4'))
        self.assertEqual(rec.basic_pay, Decimal('1000.00'))

    def test_half_day_pays_half(self):
        self._record_with(_MAY_19, 'half_day', time_in=datetime.time(8, 0))
        self._generate()
        rec = self._record()
        self.assertEqual(rec.payable_days, Decimal('0.5'))
        self.assertEqual(rec.basic_pay, Decimal('500.00'))

    def test_explicit_absent_is_docked(self):
        self._record_with(_MAY_19, 'absent', time_in=datetime.time(8, 0))
        self._generate()
        rec = self._record()
        self.assertEqual(rec.present_days, 0)
        self.assertEqual(rec.absent_days, Decimal('5'))

    def test_on_leave_status_not_counted_as_absent(self):
        # On-leave day (no LeaveRequest) is neutral: not paid here, not docked as absent.
        self._record_with(_MAY_19, 'on_leave')
        self._generate()
        rec = self._record()
        self.assertEqual(rec.absent_days, Decimal('4'))
        self.assertEqual(rec.present_days, 0)


# ── Attendance counts even without a WorkSchedule ───────────────────────────────

class NoScheduleAttendanceTest(TestCase):
    """
    An employee with NO WorkSchedule must still be paid from actual attendance.
    Mirrors a live bug where present/payable/basic were 0 despite clock-ins.
    """

    def setUp(self):
        self.company = Company.objects.create(name='No-Sched Co', email='ns@test.com')
        self.emp = Employee.objects.create(
            company=self.company, employee_id='NS001',
            first_name='Test', last_name='Employee', email='ns@test.com',
            date_hired=datetime.date(2024, 1, 1),
            basic_salary=Decimal('25000.00'), pay_basis='daily', status='active',
            # no work_schedule on purpose; 25000 mirrors the live record
        )
        self.period = PayrollPeriod.objects.create(
            company=self.company, name='June',
            start_date=datetime.date(2026, 6, 1), end_date=datetime.date(2026, 6, 30),
        )

    def test_attendance_and_worked_holiday_counted(self):
        from holidays.models import Holiday
        for d in (15, 16, 17):
            AttendanceRecord.objects.create(
                company=self.company, employee=self.emp,
                date=datetime.date(2026, 6, d),
                time_in=datetime.time(8, 0), time_out=datetime.time(17, 0),
                total_hours=Decimal('9.00'), status='present',
            )
        Holiday.objects.create(
            company=self.company, name='TEST HOLIDAY', date=datetime.date(2026, 6, 15),
            is_enabled=True, is_paid=True,
            no_work_pay_pct=Decimal('100.00'), worked_multiplier=Decimal('2.00'),
        )

        generate_payroll_for_period(self.period)
        rec = PayrollRecord.objects.get(payroll_period=self.period, employee=self.emp)

        # Jun 16 & 17 are regular present days; Jun 15 is the worked holiday.
        self.assertEqual(rec.present_days, 2)
        self.assertEqual(rec.payable_days, Decimal('2'))
        self.assertEqual(rec.absent_days, Decimal('0'))   # no schedule → no phantom absences
        self.assertEqual(rec.basic_pay, Decimal('1923.08'))
        self.assertEqual(rec.holiday_worked_days, 1)
        self.assertEqual(rec.holiday_pay, Decimal('1923.08'))
        self.assertEqual(rec.gross_pay, Decimal('3846.16'))
        self.assertNotEqual(rec.basic_pay, Decimal('0'))


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

    def test_no_ot_overtime_is_not_paid_even_with_actual_overtime(self):
        emp = self._emp('no_ot')
        self._attendance(emp, 120)
        rec = self._record(emp)
        self.assertEqual(rec.overtime_minutes, 0)
        self.assertEqual(rec.overtime_pay, Decimal('0.00'))

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

    def test_request_required_pays_min_approved_and_actual(self):
        emp = self._emp('request_required')
        self._attendance(emp, 60)
        OvertimeRequest.objects.create(
            company=self.company, employee=emp, date=self.day,
            requested_hours=Decimal('2.00'), approved_hours=Decimal('2.00'),
            status='approved', source='employee',
        )
        rec = self._record(emp)
        self.assertEqual(rec.overtime_minutes, 60)
        self.assertEqual(rec.overtime_pay, Decimal('156.25'))

    def test_approved_overtime_without_actual_overtime_pays_zero(self):
        emp = self._emp('request_required')
        self._attendance(emp, 0)
        OvertimeRequest.objects.create(
            company=self.company, employee=emp, date=self.day,
            requested_hours=Decimal('2.00'), approved_hours=Decimal('2.00'),
            status='approved', source='employee',
        )
        rec = self._record(emp)
        self.assertEqual(rec.overtime_minutes, 0)
        self.assertEqual(rec.overtime_pay, Decimal('0.00'))

    def test_multiple_approved_requests_do_not_pay_beyond_actual_overtime(self):
        emp = self._emp('request_required')
        self._attendance(emp, 120)
        OvertimeRequest.objects.create(
            company=self.company, employee=emp, date=self.day,
            requested_hours=Decimal('1.00'), approved_hours=Decimal('1.00'),
            status='approved', source='employee',
        )
        OvertimeRequest.objects.create(
            company=self.company, employee=emp, date=self.day,
            requested_hours=Decimal('2.00'), approved_hours=Decimal('2.00'),
            status='approved', source='hr',
        )
        rec = self._record(emp)
        self.assertEqual(rec.overtime_minutes, 120)
        self.assertEqual(rec.overtime_pay, Decimal('312.50'))


# ── Test 14: PayrollAdjustment deduction reflected in total_deductions ────────

class FlexiblePayrollIntegrationTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(
            name='Flexible Payroll Co',
            email='flexpay@test.com',
        )
        self.day = datetime.date(2026, 6, 1)
        self.period = PayrollPeriod.objects.create(
            company=self.company,
            name='Flexible Day',
            start_date=self.day,
            end_date=self.day,
        )

    def _employee(self, **overrides):
        data = {
            'company': self.company,
            'employee_id': f'FLEX-{Employee.objects.count() + 1}',
            'first_name': 'Flex',
            'last_name': 'Worker',
            'email': 'flex@test.com',
            'date_hired': datetime.date(2024, 1, 1),
            'basic_salary': Decimal('26000.00'),
            'status': 'active',
            'attendance_policy_type': Employee.ATTENDANCE_POLICY_FLEXIBLE,
            'flexible_schedule_enabled': True,
            'required_daily_hours': Decimal('8.00'),
            'default_break_minutes': 0,
            'flexible_overtime_grace_minutes': 30,
            'overtime_policy': 'automatic',
        }
        data.update(overrides)
        return Employee.objects.create(**data)

    def _attendance(self, employee, time_in, time_out):
        record = AttendanceRecord.objects.create(
            company=self.company,
            employee=employee,
            date=self.day,
            time_in=time_in,
            time_out=time_out,
            status='present',
        )
        compute_attendance(record)
        record.refresh_from_db()
        return record

    def _payroll_record(self, employee):
        generate_payroll_for_period(self.period)
        return PayrollRecord.objects.get(payroll_period=self.period, employee=employee)

    def test_flexible_eight_hours_twenty_minutes_has_no_overtime_pay(self):
        employee = self._employee()
        attendance = self._attendance(employee, datetime.time(8, 0), datetime.time(16, 20))
        self.assertEqual(attendance.overtime_minutes, 0)

        record = self._payroll_record(employee)

        self.assertEqual(record.overtime_minutes, 0)
        self.assertEqual(record.overtime_pay, Decimal('0.00'))

    def test_flexible_nine_hours_pays_thirty_overtime_minutes_when_policy_allows(self):
        employee = self._employee()
        attendance = self._attendance(employee, datetime.time(8, 0), datetime.time(17, 0))
        self.assertEqual(attendance.overtime_minutes, 30)

        record = self._payroll_record(employee)

        self.assertEqual(record.overtime_minutes, 30)
        self.assertEqual(record.overtime_pay, Decimal('78.13'))

    def test_night_differential_disabled_has_no_night_diff_pay(self):
        employee = self._employee(night_differential_enabled=False)
        attendance = self._attendance(employee, datetime.time(22, 0), datetime.time(2, 0))
        self.assertEqual(attendance.night_differential_minutes, 0)

        record = self._payroll_record(employee)

        self.assertEqual(record.night_differential_minutes, 0)
        self.assertEqual(record.night_differential_pay, Decimal('0.00'))

    def test_night_differential_enabled_pays_premium_for_ten_pm_to_two_am(self):
        employee = self._employee(
            night_differential_enabled=True,
            night_differential_percentage=Decimal('10.00'),
            night_differential_start_time=datetime.time(22, 0),
            night_differential_end_time=datetime.time(6, 0),
        )
        attendance = self._attendance(employee, datetime.time(22, 0), datetime.time(2, 0))
        self.assertEqual(attendance.night_differential_minutes, 240)

        record = self._payroll_record(employee)

        self.assertEqual(record.night_differential_minutes, 240)
        self.assertEqual(record.night_differential_pay, Decimal('50.00'))
        self.assertEqual(record.gross_pay, Decimal('1050.00'))
        self.assertEqual(record.net_pay, Decimal('550.00'))

    def test_overnight_night_differential_window_counts_full_overlap(self):
        employee = self._employee(
            night_differential_enabled=True,
            night_differential_percentage=Decimal('10.00'),
            night_differential_start_time=datetime.time(22, 0),
            night_differential_end_time=datetime.time(6, 0),
            overtime_policy='no_ot',
        )
        attendance = self._attendance(employee, datetime.time(21, 0), datetime.time(6, 0))
        self.assertEqual(attendance.night_differential_minutes, 480)

        record = self._payroll_record(employee)

        self.assertEqual(record.night_differential_minutes, 480)
        self.assertEqual(record.night_differential_pay, Decimal('100.00'))

    def test_payslip_shows_night_differential_pay_only_when_amount_exists(self):
        admin = User.objects.create_superuser(
            username='night-admin',
            email='night-admin@test.com',
            password='testpass123',
        )
        self.client.force_login(admin)

        no_night_employee = self._employee(
            employee_id='FLEX-NO-ND',
            night_differential_enabled=False,
        )
        self._attendance(no_night_employee, datetime.time(22, 0), datetime.time(2, 0))
        generate_payroll_for_period(self.period)
        no_night_record = PayrollRecord.objects.get(
            payroll_period=self.period,
            employee=no_night_employee,
        )

        response = self.client.get(reverse('payroll:payslip_view', args=[no_night_record.pk]))
        self.assertNotContains(response, 'Night Differential Pay')

        night_employee = self._employee(
            employee_id='FLEX-WITH-ND',
            night_differential_enabled=True,
            night_differential_percentage=Decimal('10.00'),
            night_differential_start_time=datetime.time(22, 0),
            night_differential_end_time=datetime.time(6, 0),
        )
        self._attendance(night_employee, datetime.time(22, 0), datetime.time(2, 0))
        generate_payroll_for_period(self.period)
        night_record = PayrollRecord.objects.get(
            payroll_period=self.period,
            employee=night_employee,
        )

        response = self.client.get(reverse('payroll:payslip_view', args=[night_record.pk]))
        self.assertContains(response, 'Night Differential Pay')
        self.assertContains(response, '&#8369;50.00')

    def test_regenerate_updates_stale_draft_night_differential_totals(self):
        employee = self._employee(
            night_differential_enabled=True,
            night_differential_percentage=Decimal('10.00'),
            night_differential_start_time=datetime.time(22, 0),
            night_differential_end_time=datetime.time(6, 0),
        )
        self._attendance(employee, datetime.time(22, 0), datetime.time(2, 0))
        generate_payroll_for_period(self.period)
        record = PayrollRecord.objects.get(payroll_period=self.period, employee=employee)

        PayrollRecord.objects.filter(pk=record.pk).update(
            night_differential_minutes=0,
            night_differential_pay=Decimal('0.00'),
            gross_pay=Decimal('0.00'),
            net_pay=Decimal('0.00'),
        )

        created, updated, skipped = generate_payroll_for_period(self.period)
        record.refresh_from_db()

        self.assertEqual((created, updated, skipped), (0, 1, 0))
        self.assertEqual(record.night_differential_minutes, 240)
        self.assertEqual(record.night_differential_pay, Decimal('50.00'))
        self.assertEqual(record.gross_pay, Decimal('1050.00'))


class AdjustmentDeductionTotalTest(PayrollV2TestCase):
    """
    Regression: PayrollAdjustment deductions must appear in total_deductions
    and reduce net_pay.  The live bug was that:
      - record.gross_pay = 500, record.net_pay = 500  (no standard deductions)
      - PayrollAdjustment(type='deduction', amount=20) existed
      - total_deductions (computed as gross_pay - net_pay) remained 0
      - net_pay remained 500

    Root cause 1: PayrollRecordForm.save() recomputed gross/net without calling
                  recalculate(), silently wiping adjustment effects on save.
    Root cause 2: portal/views.py portal_payslip_detail never passed
                  total_deductions to the template context, so the template
                  always rendered just "₱" (peso sign + empty string).
    """

    def test_deduction_adjustment_reduces_net_and_total(self):
        """recalculate() must include deduction adjustments in net_pay."""
        for d in (_MAY_19, _MAY_20, _MAY_21, _MAY_22, _MAY_23):
            self._clock_in(d)
        self._generate()
        rec = self._record()

        self.assertEqual(rec.gross_pay, Decimal('5000.00'))
        self.assertEqual(rec.net_pay,   Decimal('5000.00'))

        PayrollAdjustment.objects.create(
            payroll_record=rec,
            name='Cash Advance',
            adjustment_type='deduction',
            amount=Decimal('500.00'),
        )
        rec.recalculate()
        rec.refresh_from_db()

        self.assertEqual(rec.gross_pay, Decimal('5000.00'))   # gross unchanged
        self.assertEqual(rec.net_pay,   Decimal('4500.00'))   # deducted
        # total_deductions as computed in both payslip views (gross - net)
        total_deductions = rec.gross_pay - rec.net_pay
        self.assertEqual(total_deductions, Decimal('500.00'))

    def test_adjustment_save_and_delete_refresh_record_totals(self):
        """Adjustment writes should keep the parent PayrollRecord totals current."""
        for d in (_MAY_19, _MAY_20, _MAY_21, _MAY_22, _MAY_23):
            self._clock_in(d)
        self._generate()
        rec = self._record()

        adj = PayrollAdjustment.objects.create(
            payroll_record=rec,
            name='Uniform Deduction',
            adjustment_type='deduction',
            amount=Decimal('250.00'),
        )
        rec.refresh_from_db()
        self.assertEqual(rec.gross_pay, Decimal('5000.00'))
        self.assertEqual(rec.net_pay, Decimal('4750.00'))

        adj.amount = Decimal('400.00')
        adj.save()
        rec.refresh_from_db()
        self.assertEqual(rec.net_pay, Decimal('4600.00'))

        adj.delete()
        rec.refresh_from_db()
        self.assertEqual(rec.gross_pay, Decimal('5000.00'))
        self.assertEqual(rec.net_pay, Decimal('5000.00'))

    def test_views_use_calculated_totals_when_saved_totals_are_stale(self):
        """
        Payslip and list displays must use the shared calculated totals, not just
        cached gross_pay/net_pay fields.
        """
        for d in (_MAY_19, _MAY_20, _MAY_21, _MAY_22, _MAY_23):
            self._clock_in(d)
        self._generate()
        rec = self._record()
        PayrollAdjustment.objects.create(
            payroll_record=rec,
            name='Cash Advance',
            adjustment_type='deduction',
            amount=Decimal('500.00'),
        )
        PayrollAdjustment.objects.create(
            payroll_record=rec,
            name='Bonus',
            adjustment_type='earning',
            amount=Decimal('1000.00'),
        )

        # Simulate stale persisted totals from older records or external writes.
        PayrollRecord.objects.filter(pk=rec.pk).update(
            gross_pay=Decimal('5000.00'),
            net_pay=Decimal('5000.00'),
        )

        admin = User.objects.create_superuser(
            username='payroll-admin',
            email='payroll-admin@test.com',
            password='testpass123',
        )
        self.client.force_login(admin)

        detail = self.client.get(reverse('payroll:payslip_view', args=[rec.pk]))
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.context['gross_pay'], Decimal('6000.00'))
        self.assertEqual(detail.context['total_deductions'], Decimal('500.00'))
        self.assertEqual(detail.context['net_pay'], Decimal('5500.00'))

        listing = self.client.get(reverse('payroll:payroll_record_list'))
        self.assertEqual(listing.status_code, 200)
        listed = next(r for r in listing.context['records'] if r.pk == rec.pk)
        self.assertEqual(listed.display_gross_pay, Decimal('6000.00'))
        self.assertEqual(listed.display_net_pay, Decimal('5500.00'))

    def test_rate_information_only_shows_rates_for_present_pay_types(self):
        """Do not show hourly or OT rates unless the related payslip row exists."""
        for d in (_MAY_19, _MAY_20, _MAY_21, _MAY_22, _MAY_23):
            self._clock_in(d)
        self._generate()
        rec = self._record()

        admin = User.objects.create_superuser(
            username='rate-admin',
            email='rate-admin@test.com',
            password='testpass123',
        )
        self.client.force_login(admin)

        response = self.client.get(reverse('payroll:payslip_view', args=[rec.pk]))
        self.assertContains(response, 'Daily Rate')
        self.assertNotContains(response, 'Hourly Rate')
        self.assertNotContains(response, 'Regular O.T. Rate')

        PayrollRecord.objects.filter(pk=rec.pk).update(
            holiday_pay=Decimal('1000.00'),
            holiday_worked_days=1,
        )
        response = self.client.get(reverse('payroll:payslip_view', args=[rec.pk]))
        self.assertContains(response, 'Holiday Pay')
        self.assertNotContains(response, 'Rest Day / Sp. Holiday O.T.')
        self.assertNotContains(response, 'Regular Holiday O.T.')

    def test_form_save_preserves_adjustment_deduction(self):
        """
        Editing a PayrollRecord via PayrollRecordForm must not overwrite
        net_pay back to a value that excludes PayrollAdjustments.
        Previously, form.save() did its own gross/net math without calling
        recalculate(), so any subsequent form save would silently reset
        net_pay to gross_pay (making total_deductions appear as 0).
        """
        from payroll.forms import PayrollRecordForm

        for d in (_MAY_19, _MAY_20, _MAY_21, _MAY_22, _MAY_23):
            self._clock_in(d)
        self._generate()
        rec = self._record()

        # Add a deduction adjustment and confirm it is reflected.
        PayrollAdjustment.objects.create(
            payroll_record=rec,
            name='Loan Repayment',
            adjustment_type='deduction',
            amount=Decimal('200.00'),
        )
        rec.recalculate()
        rec.refresh_from_db()
        self.assertEqual(rec.net_pay, Decimal('4800.00'))

        # Simulate a user editing and saving the record through the admin form.
        form_data = {
            'company':               rec.company_id,
            'payroll_period':        rec.payroll_period_id,
            'employee':              rec.employee_id,
            'basic_pay':             str(rec.basic_pay),
            'allowances':            '0',
            'overtime_pay':          '0',
            'sss_deduction':         '0',
            'philhealth_deduction':  '0',
            'pagibig_deduction':     '0',
            'tax_deduction':         '0',
            'late_deduction':        '0',
            'undertime_deduction':   '0',
            'absence_deduction':     '0',
            'other_deductions':      '0',
            'status':                rec.status,
        }
        form = PayrollRecordForm(form_data, instance=rec)
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        saved.refresh_from_db()

        # net_pay must still reflect the ₱200 deduction adjustment.
        self.assertEqual(saved.net_pay, Decimal('4800.00'))
        total_deductions = saved.gross_pay - saved.net_pay
        self.assertEqual(total_deductions, Decimal('200.00'))

    def test_earning_adjustment_increases_gross_and_net(self):
        """Earning adjustments must raise both gross_pay and net_pay."""
        for d in (_MAY_19, _MAY_20, _MAY_21, _MAY_22, _MAY_23):
            self._clock_in(d)
        self._generate()
        rec = self._record()

        PayrollAdjustment.objects.create(
            payroll_record=rec,
            name='Performance Bonus',
            adjustment_type='earning',
            amount=Decimal('1000.00'),
        )
        rec.recalculate()
        rec.refresh_from_db()

        self.assertEqual(rec.gross_pay, Decimal('6000.00'))
        self.assertEqual(rec.net_pay,   Decimal('6000.00'))

    def test_regenerate_respects_existing_adjustments(self):
        """
        After regenerating a draft period that already has adjustments,
        recalculate() is called inside generate_payroll_for_period and the
        adjustments must still be reflected in net_pay.
        """
        for d in (_MAY_19, _MAY_20, _MAY_21, _MAY_22, _MAY_23):
            self._clock_in(d)
        self._generate()
        rec = self._record()

        PayrollAdjustment.objects.create(
            payroll_record=rec,
            name='SSS Loan',
            adjustment_type='deduction',
            amount=Decimal('300.00'),
        )
        rec.recalculate()

        # Regenerate — should preserve the ₱300 deduction.
        self._generate()
        rec.refresh_from_db()
        self.assertEqual(rec.net_pay, Decimal('4700.00'))
