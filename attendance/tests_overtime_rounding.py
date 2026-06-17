"""
Tests for the Overtime Counting / Rounding Rule feature.

Overtime can be counted by completed blocks (30 min / 1 hr / 2 hr) instead of
exact minutes. Counting always floors DOWN to the last completed block; it never
rounds up. The raw detected overtime is preserved in
``AttendanceRecord.actual_overtime_minutes`` while ``overtime_minutes`` (which
payroll sums) holds the counted/payable value.
"""

import datetime
from decimal import Decimal

from django.test import TestCase

from companies.models import Company
from employees.models import Employee
from .models import AttendanceRecord, WorkSchedule
from .services import apply_overtime_rule, compute_attendance, resolve_overtime_rule


# ──────────────────────────────────────────────────────────────────────────────
# Pure rounding function
# ──────────────────────────────────────────────────────────────────────────────

class ApplyOvertimeRuleTests(TestCase):
    def test_exact_mode_keeps_actual(self):
        # Scenario 3: exact mode keeps current behavior.
        self.assertEqual(apply_overtime_rule(105, 'exact'), 105)

    def test_blank_rule_keeps_actual(self):
        self.assertEqual(apply_overtime_rule(105, ''), 105)

    def test_29_minutes_becomes_0(self):
        # Scenario 4
        self.assertEqual(apply_overtime_rule(29, '30'), 0)

    def test_5_minutes_becomes_0(self):
        self.assertEqual(apply_overtime_rule(5, '30'), 0)

    def test_30_minutes_becomes_30(self):
        # Scenario 5
        self.assertEqual(apply_overtime_rule(30, '30'), 30)

    def test_59_minutes_becomes_30(self):
        self.assertEqual(apply_overtime_rule(59, '30'), 30)

    def test_89_minutes_becomes_60(self):
        # Scenario 6 (1 hr 25 min → 1 hr)
        self.assertEqual(apply_overtime_rule(89, '30'), 60)
        self.assertEqual(apply_overtime_rule(85, '30'), 60)

    def test_105_minutes_becomes_90(self):
        # Scenario 7 (1 hr 45 min → 1 hr 30 min)
        self.assertEqual(apply_overtime_rule(105, '30'), 90)

    def test_130_minutes_becomes_120_under_30_rule(self):
        # 2 hr 10 min → 2 hr
        self.assertEqual(apply_overtime_rule(130, '30'), 120)

    def test_one_hour_blocks_floor_down(self):
        self.assertEqual(apply_overtime_rule(59, '60'), 0)
        self.assertEqual(apply_overtime_rule(60, '60'), 60)
        self.assertEqual(apply_overtime_rule(119, '60'), 60)
        self.assertEqual(apply_overtime_rule(120, '60'), 120)

    def test_two_hour_blocks_floor_down(self):
        self.assertEqual(apply_overtime_rule(119, '120'), 0)
        self.assertEqual(apply_overtime_rule(120, '120'), 120)
        self.assertEqual(apply_overtime_rule(239, '120'), 120)

    def test_zero_overtime_stays_zero(self):
        self.assertEqual(apply_overtime_rule(0, '30'), 0)


# ──────────────────────────────────────────────────────────────────────────────
# Rule resolution (employee override → company default → exact)
# ──────────────────────────────────────────────────────────────────────────────

class ResolveOvertimeRuleTests(TestCase):
    def _employee(self, company_rule='', employee_rule=''):
        company = Company.objects.create(
            name='Co', default_overtime_counting_rule=company_rule or 'exact',
        )
        emp = Employee.objects.create(
            company=company, employee_id='E1', first_name='A', last_name='B',
            date_hired=datetime.date(2024, 1, 1), status='active',
            overtime_counting_rule=employee_rule,
        )
        return emp

    def test_employee_inherits_company_rule(self):
        # Scenario 1
        emp = self._employee(company_rule='30', employee_rule='')
        self.assertEqual(resolve_overtime_rule(emp), '30')

    def test_employee_override_beats_company(self):
        # Scenario 2
        emp = self._employee(company_rule='60', employee_rule='30')
        self.assertEqual(resolve_overtime_rule(emp), '30')

    def test_company_exact_when_nothing_set(self):
        emp = self._employee(company_rule='exact', employee_rule='')
        self.assertEqual(resolve_overtime_rule(emp), 'exact')


# ──────────────────────────────────────────────────────────────────────────────
# Integration: compute_attendance writes raw + counted overtime
# ──────────────────────────────────────────────────────────────────────────────

class OvertimeRoundingComputeTests(TestCase):
    """A flexible employee working 08:00–18:45 (60 min break) earns 105 raw OT
    minutes (585 worked − 480 required − 0 grace)."""

    def _setup(self, company_rule='exact', employee_rule=''):
        company = Company.objects.create(
            name='Flex Co', default_overtime_counting_rule=company_rule,
        )
        schedule = WorkSchedule.objects.create(
            company=company, name='Std',
            start_time=datetime.time(8, 0), end_time=datetime.time(17, 0),
            grace_minutes=15, break_minutes=60, required_hours=Decimal('8.00'),
        )
        emp = Employee.objects.create(
            company=company, employee_id='F1', first_name='Flex', last_name='Emp',
            date_hired=datetime.date(2024, 1, 1), status='active',
            attendance_policy_type='flexible', required_daily_hours=Decimal('8.00'),
            default_break_minutes=60, flexible_overtime_grace_minutes=0,
            overtime_counting_rule=employee_rule,
        )
        emp.work_schedule = schedule
        emp.save(update_fields=['work_schedule'])
        rec = AttendanceRecord.objects.create(
            company=company, employee=emp,
            date=datetime.date(2026, 5, 25),  # Monday
            time_in=datetime.time(8, 0), time_out=datetime.time(18, 45),
            break_minutes=60, status='present',
        )
        return rec

    def test_exact_keeps_current_behavior(self):
        # Scenario 3: counted == actual when exact.
        rec = self._setup(company_rule='exact')
        compute_attendance(rec)
        rec.refresh_from_db()
        self.assertEqual(rec.actual_overtime_minutes, 105)
        self.assertEqual(rec.overtime_minutes, 105)

    def test_inherited_company_rule_rounds_down(self):
        # Scenario 1 + 9: actual preserved, counted floored to 90.
        rec = self._setup(company_rule='30', employee_rule='')
        compute_attendance(rec)
        rec.refresh_from_db()
        self.assertEqual(rec.actual_overtime_minutes, 105)
        self.assertEqual(rec.overtime_minutes, 90)
        self.assertEqual(rec.overtime_hours, Decimal('1.50'))

    def test_employee_override_beats_company_in_compute(self):
        # Scenario 2: company 60-min would give 60; employee 30-min gives 90.
        rec = self._setup(company_rule='60', employee_rule='30')
        compute_attendance(rec)
        rec.refresh_from_db()
        self.assertEqual(rec.actual_overtime_minutes, 105)
        self.assertEqual(rec.overtime_minutes, 90)


# ──────────────────────────────────────────────────────────────────────────────
# Display helpers used by the attendance list / clock badges
# ──────────────────────────────────────────────────────────────────────────────

class OvertimeDisplayHelperTests(TestCase):
    def _record(self, counted=0, actual=0):
        return AttendanceRecord(overtime_minutes=counted, actual_overtime_minutes=actual)

    def test_format_hours_and_minutes(self):
        self.assertEqual(self._record(counted=90).overtime_counted_display, '1h 30m')

    def test_format_whole_hours_only(self):
        self.assertEqual(self._record(counted=120).overtime_counted_display, '2h')

    def test_format_minutes_only(self):
        self.assertEqual(self._record(counted=45).overtime_counted_display, '45m')

    def test_format_zero(self):
        self.assertEqual(self._record(counted=0).overtime_counted_display, '0m')

    def test_actual_overtime_display(self):
        self.assertEqual(self._record(actual=105).actual_overtime_display, '1h 45m')

    def test_overtime_counting_reduced_true_when_actual_exceeds_counted(self):
        self.assertTrue(self._record(counted=90, actual=105).overtime_counting_reduced)

    def test_overtime_counting_reduced_false_when_equal(self):
        self.assertFalse(self._record(counted=105, actual=105).overtime_counting_reduced)


# ──────────────────────────────────────────────────────────────────────────────
# Integration: payroll sums the counted overtime_minutes
# ──────────────────────────────────────────────────────────────────────────────

class OvertimeRoundingPayrollTests(TestCase):
    """Payroll already sums AttendanceRecord.overtime_minutes, so storing the
    counted value there means payroll pays the counted overtime automatically."""

    def test_payroll_uses_counted_overtime(self):
        # Scenario 8
        from payroll.models import PayrollPeriod, PayrollRecord
        from payroll.services import generate_payroll_for_period

        company = Company.objects.create(
            name='Pay Co', default_overtime_counting_rule='30',
        )
        schedule = WorkSchedule.objects.create(
            company=company, name='Std',
            start_time=datetime.time(8, 0), end_time=datetime.time(17, 0),
            grace_minutes=15, break_minutes=60, required_hours=Decimal('8.00'),
        )
        emp = Employee.objects.create(
            company=company, employee_id='PR1', first_name='Pay', last_name='Roll',
            date_hired=datetime.date(2024, 1, 1), status='active',
            basic_salary=Decimal('26000.00'),  # daily 1000, hourly 125
            overtime_policy='automatic',
        )
        emp.work_schedule = schedule
        emp.save(update_fields=['work_schedule'])

        day = datetime.date(2026, 5, 25)  # Monday
        # 08:00–18:45 on a fixed shift ending 17:00 → 105 raw OT minutes.
        rec = AttendanceRecord.objects.create(
            company=company, employee=emp, date=day,
            time_in=datetime.time(8, 0), time_out=datetime.time(18, 45),
            break_minutes=60, status='present',
        )
        compute_attendance(rec)
        rec.refresh_from_db()
        self.assertEqual(rec.actual_overtime_minutes, 105)
        self.assertEqual(rec.overtime_minutes, 90)  # counted

        period = PayrollPeriod.objects.create(
            company=company, name='May D1', start_date=day, end_date=day,
        )
        generate_payroll_for_period(period)
        pr = PayrollRecord.objects.get(payroll_period=period, employee=emp)
        self.assertEqual(pr.overtime_minutes, 90)
