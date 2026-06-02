import base64
import datetime
import io
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from django.utils import timezone
from PIL import Image

from companies.models import Company
from employees.models import Employee
from .models import AttendanceLocation, AttendancePortalLog, AttendanceRecord, BiometricDevice, BiometricLog, WorkSchedule
from .services import compute_attendance
from .biometric_services import (
    create_biometric_log,
    mark_log_processed,
    match_employee_for_biometric_log,
)
from .portal_services import (
    can_employee_clock_from_request,
    find_matching_attendance_location,
    ip_matches_location,
)


def _make_company():
    return Company.objects.create(name='Test Co')


def _make_schedule(company, **kwargs):
    defaults = dict(
        name='Standard',
        start_time=datetime.time(8, 0),
        end_time=datetime.time(17, 0),
        grace_minutes=15,
        break_minutes=60,
        required_hours=Decimal('8.00'),
        overtime_after=None,
    )
    defaults.update(kwargs)
    return WorkSchedule.objects.create(company=company, **defaults)


_emp_counter = 0


def _make_employee(company, schedule=None):
    global _emp_counter
    _emp_counter += 1
    emp = Employee.objects.create(
        company=company,
        employee_id=f'T{_emp_counter:03d}',
        first_name='Test',
        last_name='Employee',
        date_hired=datetime.date(2024, 1, 1),
        status='active',
    )
    if schedule:
        emp.work_schedule = schedule
        emp.save(update_fields=['work_schedule'])
    return emp


def _make_record(employee, date=None, time_in=None, time_out=None, break_minutes=60):
    return AttendanceRecord.objects.create(
        company=employee.company,
        employee=employee,
        date=date or datetime.date(2026, 5, 26),  # Monday
        time_in=time_in,
        time_out=time_out,
        break_minutes=break_minutes,
        status='present',
    )


class ComputeAttendanceTotalHoursTests(TestCase):
    def setUp(self):
        self.company = _make_company()
        self.schedule = _make_schedule(self.company)
        self.employee = _make_employee(self.company, self.schedule)

    def test_total_hours_set_from_work_minutes(self):
        # 8:00 in, 17:00 out, 60 min break → 8h net
        record = _make_record(
            self.employee,
            time_in=datetime.time(8, 0),
            time_out=datetime.time(17, 0),
            break_minutes=60,
        )
        compute_attendance(record)
        record.refresh_from_db()
        self.assertEqual(record.total_hours, Decimal('8.00'))
        self.assertEqual(record.total_work_minutes, 480)

    def test_overtime_hours_set_correctly(self):
        # 8:00 in, 19:00 out, 60 min break → 10h net, 2h overtime (after 17:00)
        record = _make_record(
            self.employee,
            time_in=datetime.time(8, 0),
            time_out=datetime.time(19, 0),
            break_minutes=60,
        )
        compute_attendance(record)
        record.refresh_from_db()
        self.assertEqual(record.overtime_hours, Decimal('2.00'))
        self.assertEqual(record.overtime_minutes, 120)
        self.assertEqual(record.computed_status, 'overtime')

    def test_no_overtime_when_on_time(self):
        record = _make_record(
            self.employee,
            time_in=datetime.time(8, 0),
            time_out=datetime.time(17, 0),
            break_minutes=60,
        )
        compute_attendance(record)
        record.refresh_from_db()
        self.assertEqual(record.overtime_hours, Decimal('0.00'))
        self.assertEqual(record.overtime_minutes, 0)
        self.assertEqual(record.computed_status, 'present')

    def test_undertime_sets_zero_total_hours_proportionally(self):
        # 8:00 in, 13:00 out, 60 min break → 4h net (undertime)
        record = _make_record(
            self.employee,
            time_in=datetime.time(8, 0),
            time_out=datetime.time(13, 0),
            break_minutes=60,
        )
        compute_attendance(record)
        record.refresh_from_db()
        self.assertEqual(record.total_hours, Decimal('4.00'))
        self.assertEqual(record.computed_status, 'undertime')

    def test_within_grace_late_minutes_is_zero(self):
        # 08:14 in: start=08:00, grace=15 min → cutoff is 08:15 → not late
        record = _make_record(
            self.employee,
            time_in=datetime.time(8, 14),
            time_out=datetime.time(17, 0),
            break_minutes=60,
        )
        compute_attendance(record)
        record.refresh_from_db()
        self.assertEqual(record.late_minutes, 0)

    def test_after_grace_late_minutes_counted(self):
        # 08:20 in: grace cutoff is 08:15 → 5 min late
        record = _make_record(
            self.employee,
            time_in=datetime.time(8, 20),
            time_out=datetime.time(17, 0),
            break_minutes=60,
        )
        compute_attendance(record)
        record.refresh_from_db()
        self.assertEqual(record.late_minutes, 5)
        # Undertime dominates status (arrived late + left on time = short hours)
        self.assertEqual(record.computed_status, 'undertime')

    def test_no_schedule_still_sets_total_hours(self):
        emp_no_sched = _make_employee(self.company, schedule=None)
        record = _make_record(
            emp_no_sched,
            time_in=datetime.time(9, 0),
            time_out=datetime.time(18, 0),
            break_minutes=0,
        )
        compute_attendance(record)
        record.refresh_from_db()
        self.assertEqual(record.total_work_minutes, 540)
        self.assertEqual(record.total_hours, Decimal('9.00'))
        self.assertEqual(record.computed_status, 'present')

    def test_missing_timeout_gives_incomplete(self):
        record = _make_record(
            self.employee,
            time_in=datetime.time(8, 0),
            time_out=None,
        )
        compute_attendance(record)
        record.refresh_from_db()
        self.assertEqual(record.computed_status, 'incomplete')
        self.assertEqual(record.total_hours, Decimal('0.00'))

    def test_missing_timein_gives_absent(self):
        record = _make_record(self.employee, time_in=None, time_out=None)
        compute_attendance(record)
        record.refresh_from_db()
        self.assertEqual(record.computed_status, 'absent')


class AttendanceAccessTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(
            username='admin_test', password='testpass123'
        )

    def test_attendance_list_requires_login(self):
        response = self.client.get(reverse('attendance:attendance_list'))
        self.assertIn(response.status_code, [302, 403])


# ---------------------------------------------------------------------------
# Company-scoped attendance monitoring tests
# ---------------------------------------------------------------------------

from accounts.models import UserCompanyAccess, UserProfile


def _setup_two_companies():
    """Return (company_a, company_b, employee_a, employee_b)."""
    co_a = Company.objects.create(name='Alpha Corp')
    co_b = Company.objects.create(name='Beta Corp')
    emp_a = Employee.objects.create(
        company=co_a, employee_id='A001', first_name='Alice', last_name='Alpha',
        date_hired=datetime.date(2024, 1, 1), status='active',
    )
    emp_b = Employee.objects.create(
        company=co_b, employee_id='B001', first_name='Bob', last_name='Beta',
        date_hired=datetime.date(2024, 1, 1), status='active',
    )
    return co_a, co_b, emp_a, emp_b


class AttendanceCompanyScopeTests(TestCase):
    """Verify attendance list + recent-json respect company isolation."""

    def setUp(self):
        self.co_a, self.co_b, self.emp_a, self.emp_b = _setup_two_companies()

        # Superuser
        self.superuser = User.objects.create_superuser('su_att', password='testpass123')

        # User assigned only to Company A
        self.user_a = User.objects.create_user('user_att_a', password='testpass123')
        UserCompanyAccess.objects.create(user=self.user_a, company=self.co_a, role='hr_admin', is_active=True)
        UserProfile.objects.create(
            user=self.user_a, role='hr_admin', is_active_stafforyx=True,
            can_manage_attendance=True,
        )

        # Today's records for both companies
        today = datetime.date.today()
        self.record_a = AttendanceRecord.objects.create(
            company=self.co_a, employee=self.emp_a, date=today,
            time_in=datetime.time(8, 0), status='present',
        )
        self.record_b = AttendanceRecord.objects.create(
            company=self.co_b, employee=self.emp_b, date=today,
            time_in=datetime.time(8, 0), status='present',
        )

    # -- attendance_list view --

    def test_superuser_sees_records_from_all_companies(self):
        self.client.login(username='su_att', password='testpass123')
        response = self.client.get(reverse('attendance:attendance_list'))
        self.assertEqual(response.status_code, 200)
        pks = [r.pk for r in response.context['records']]
        self.assertIn(self.record_a.pk, pks)
        self.assertIn(self.record_b.pk, pks)

    def test_user_a_only_sees_company_a_records(self):
        self.client.login(username='user_att_a', password='testpass123')
        response = self.client.get(reverse('attendance:attendance_list'))
        self.assertEqual(response.status_code, 200)
        pks = [r.pk for r in response.context['records']]
        self.assertIn(self.record_a.pk, pks)
        self.assertNotIn(self.record_b.pk, pks)

    def test_superuser_selecting_company_a_filters_live_and_records(self):
        self.client.login(username='su_att', password='testpass123')
        session = self.client.session
        session['selected_company_id'] = self.co_a.pk
        session.save()
        response = self.client.get(reverse('attendance:attendance_list'))
        self.assertEqual(response.status_code, 200)
        pks = [r.pk for r in response.context['records']]
        self.assertIn(self.record_a.pk, pks)
        self.assertNotIn(self.record_b.pk, pks)
        # show_company_column is False when a specific company is selected
        self.assertFalse(response.context['show_company_column'])

    def test_superuser_all_companies_sets_show_company_column(self):
        self.client.login(username='su_att', password='testpass123')
        # No session company → all companies
        response = self.client.get(reverse('attendance:attendance_list'))
        self.assertTrue(response.context['show_company_column'])

    def test_employee_dropdown_scoped_to_selected_company(self):
        self.client.login(username='su_att', password='testpass123')
        session = self.client.session
        session['selected_company_id'] = self.co_a.pk
        session.save()
        response = self.client.get(reverse('attendance:attendance_list'))
        emp_pks = [e.pk for e in response.context['employees']]
        self.assertIn(self.emp_a.pk, emp_pks)
        self.assertNotIn(self.emp_b.pk, emp_pks)

    # -- recent-json endpoint --

    def test_recent_json_user_a_does_not_leak_company_b(self):
        self.client.login(username='user_att_a', password='testpass123')
        response = self.client.get(reverse('attendance:attendance_recent_json'))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        emp_ids = [r['employee_id'] for r in data['records']]
        self.assertIn('A001', emp_ids)
        self.assertNotIn('B001', emp_ids)

    def test_recent_json_superuser_all_includes_both(self):
        self.client.login(username='su_att', password='testpass123')
        response = self.client.get(reverse('attendance:attendance_recent_json'))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        emp_ids = [r['employee_id'] for r in data['records']]
        self.assertIn('A001', emp_ids)
        self.assertIn('B001', emp_ids)
        self.assertTrue(data['show_company'])

    def test_recent_json_superuser_company_a_selected_excludes_b(self):
        self.client.login(username='su_att', password='testpass123')
        session = self.client.session
        session['selected_company_id'] = self.co_a.pk
        session.save()
        response = self.client.get(reverse('attendance:attendance_recent_json'))
        data = response.json()
        emp_ids = [r['employee_id'] for r in data['records']]
        self.assertIn('A001', emp_ids)
        self.assertNotIn('B001', emp_ids)
        self.assertFalse(data['show_company'])

    def test_invalid_company_in_session_is_ignored_safely(self):
        """A stale or tampered session company_id that doesn't exist is cleared."""
        self.client.login(username='su_att', password='testpass123')
        session = self.client.session
        session['selected_company_id'] = 99999  # non-existent
        session.save()
        response = self.client.get(reverse('attendance:attendance_list'))
        self.assertEqual(response.status_code, 200)
        # selected_company should be None (cleared) — all companies shown
        self.assertIsNone(response.context['selected_company'])

    def test_user_a_cannot_access_company_b_via_session(self):
        """user_a sets session to co_b (not their company) — helper must reject it."""
        self.client.login(username='user_att_a', password='testpass123')
        session = self.client.session
        session['selected_company_id'] = self.co_b.pk
        session.save()
        # Still only sees company A data (get_selected_company_from_request validates access)
        response = self.client.get(reverse('attendance:attendance_recent_json'))
        data = response.json()
        emp_ids = [r['employee_id'] for r in data['records']]
        self.assertNotIn('B001', emp_ids)


# ---------------------------------------------------------------------------
# Management command tests
# ---------------------------------------------------------------------------

from io import StringIO
from django.core.management import call_command


class RecomputeAttendanceCommandTests(TestCase):
    """Tests for: python manage.py recompute_attendance"""

    def setUp(self):
        self.company = _make_company()
        self.schedule = _make_schedule(self.company)
        self.employee = _make_employee(self.company, self.schedule)

    def _make_stale_record(self, **kwargs):
        """Create a record and force total_hours/overtime_hours back to 0 to simulate stale data."""
        record = _make_record(self.employee, **kwargs)
        # Artificially zero out the computed fields so they appear "stale"
        AttendanceRecord.objects.filter(pk=record.pk).update(
            total_hours=0,
            overtime_hours=0,
            total_work_minutes=0,
            computed_status='',
        )
        record.refresh_from_db()
        return record

    # -- command exists and basic invocation --

    def test_command_runs_without_error(self):
        out = StringIO()
        call_command('recompute_attendance', stdout=out)
        # Should complete without raising

    def test_dry_run_flag_accepted(self):
        # Need at least one record for the DRY RUN banner to appear
        _make_record(
            self.employee,
            time_in=datetime.time(8, 0),
            time_out=datetime.time(17, 0),
            break_minutes=60,
        )
        out = StringIO()
        call_command('recompute_attendance', dry_run=True, stdout=out)
        self.assertIn('DRY RUN', out.getvalue())

    # -- dry-run does NOT persist changes --

    def test_dry_run_does_not_save(self):
        record = self._make_stale_record(
            time_in=datetime.time(8, 0),
            time_out=datetime.time(17, 0),
            break_minutes=60,
        )
        self.assertEqual(record.total_hours, 0)

        out = StringIO()
        call_command('recompute_attendance', dry_run=True, stdout=out)

        record.refresh_from_db()
        self.assertEqual(record.total_hours, 0)  # must still be 0 after dry-run

    # -- normal run updates fields --

    def test_normal_run_updates_total_hours(self):
        record = self._make_stale_record(
            time_in=datetime.time(8, 0),
            time_out=datetime.time(17, 0),
            break_minutes=60,
        )
        self.assertEqual(record.total_hours, 0)

        out = StringIO()
        call_command('recompute_attendance', stdout=out)

        record.refresh_from_db()
        self.assertEqual(record.total_hours, Decimal('8.00'))

    def test_normal_run_updates_overtime_hours(self):
        record = self._make_stale_record(
            time_in=datetime.time(8, 0),
            time_out=datetime.time(19, 0),  # 2h overtime
            break_minutes=60,
        )
        self.assertEqual(record.overtime_hours, 0)

        out = StringIO()
        call_command('recompute_attendance', stdout=out)

        record.refresh_from_db()
        self.assertEqual(record.overtime_hours, Decimal('2.00'))

    def test_normal_run_updates_computed_status(self):
        record = self._make_stale_record(
            time_in=datetime.time(8, 0),
            time_out=datetime.time(17, 0),
            break_minutes=60,
        )
        self.assertEqual(record.computed_status, '')

        call_command('recompute_attendance', stdout=StringIO())

        record.refresh_from_db()
        self.assertEqual(record.computed_status, 'present')

    def test_summary_shows_updated_count(self):
        self._make_stale_record(
            time_in=datetime.time(8, 0),
            time_out=datetime.time(17, 0),
            break_minutes=60,
        )
        out = StringIO()
        call_command('recompute_attendance', stdout=out)
        self.assertIn('Updated', out.getvalue())

    # -- employee-id filter --

    def test_employee_id_filter_limits_scope(self):
        # Create a second employee with a separate stale record
        emp2 = _make_employee(self.company, self.schedule)
        record1 = self._make_stale_record(
            time_in=datetime.time(8, 0),
            time_out=datetime.time(17, 0),
            break_minutes=60,
        )
        record2 = _make_record(
            emp2,
            time_in=datetime.time(8, 0),
            time_out=datetime.time(17, 0),
            break_minutes=60,
        )
        # Force record2 also stale
        AttendanceRecord.objects.filter(pk=record2.pk).update(total_hours=0, computed_status='')

        # Recompute only employee 1
        call_command(
            'recompute_attendance',
            employee_id=self.employee.employee_id,
            stdout=StringIO(),
        )

        record1.refresh_from_db()
        record2.refresh_from_db()
        self.assertEqual(record1.total_hours, Decimal('8.00'))   # updated
        self.assertEqual(record2.total_hours, 0)                  # not touched

    # -- date filters --

    def test_date_from_filter(self):
        # Create two records on different dates; only the later one should update
        record_old = self._make_stale_record(
            date=datetime.date(2026, 1, 5),   # Monday
            time_in=datetime.time(8, 0),
            time_out=datetime.time(17, 0),
            break_minutes=60,
        )
        record_new = _make_record(
            self.employee,
            date=datetime.date(2026, 5, 25),  # Monday, different week
            time_in=datetime.time(8, 0),
            time_out=datetime.time(17, 0),
            break_minutes=60,
        )
        AttendanceRecord.objects.filter(pk=record_new.pk).update(total_hours=0)

        call_command(
            'recompute_attendance',
            date_from='2026-05-01',
            stdout=StringIO(),
        )

        record_old.refresh_from_db()
        record_new.refresh_from_db()
        self.assertEqual(record_old.total_hours, 0)             # outside range, untouched
        self.assertEqual(record_new.total_hours, Decimal('8.00'))  # inside range, updated

    # -- invalid employee raises CommandError --

    def test_unknown_employee_id_raises(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            call_command('recompute_attendance', employee_id='DOESNOTEXIST', stdout=StringIO())

    # -- bad date raises CommandError --

    def test_bad_date_from_raises(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            call_command('recompute_attendance', date_from='not-a-date', stdout=StringIO())


# ---------------------------------------------------------------------------
# Biometric Device Foundation Tests
# ---------------------------------------------------------------------------

class BiometricDeviceModelTests(TestCase):
    """BiometricDevice model — basic field/constraint coverage."""

    def setUp(self):
        self.co_a = Company.objects.create(name='Alpha Corp')
        self.co_b = Company.objects.create(name='Beta Corp')

    def _make_device(self, company, code='DEV-01', **kwargs):
        return BiometricDevice.objects.create(
            company=company, name='Main Entrance', device_code=code, **kwargs
        )

    def test_device_belongs_to_company(self):
        dev = self._make_device(self.co_a)
        self.assertEqual(dev.company, self.co_a)

    def test_device_code_unique_per_company(self):
        from django.db import IntegrityError
        self._make_device(self.co_a, code='DOOR-01')
        with self.assertRaises(IntegrityError):
            self._make_device(self.co_a, code='DOOR-01')

    def test_same_device_code_allowed_in_different_companies(self):
        self._make_device(self.co_a, code='DOOR-01')
        dev_b = self._make_device(self.co_b, code='DOOR-01')
        self.assertEqual(dev_b.company, self.co_b)

    def test_device_str_shows_company_and_name(self):
        dev = self._make_device(self.co_a)
        self.assertIn('Alpha Corp', str(dev))
        self.assertIn('Main Entrance', str(dev))

    def test_is_active_default_true(self):
        dev = self._make_device(self.co_a)
        self.assertTrue(dev.is_active)

    def test_last_sync_at_nullable(self):
        dev = self._make_device(self.co_a)
        self.assertIsNone(dev.last_sync_at)


class BiometricLogModelTests(TestCase):
    """BiometricLog model and biometric_services helper tests."""

    def setUp(self):
        self.co_a = Company.objects.create(name='Alpha Corp')
        self.co_b = Company.objects.create(name='Beta Corp')

        self.dev_a = BiometricDevice.objects.create(
            company=self.co_a, name='Main Door', device_code='A-DOOR'
        )

        self.emp_a = Employee.objects.create(
            company=self.co_a,
            employee_id='A001',
            first_name='Alice',
            last_name='Alpha',
            date_hired=datetime.date(2024, 1, 1),
            status='active',
            biometric_user_id='42',
        )
        # Employee B has the SAME biometric_user_id '42' but in a different company.
        self.emp_b = Employee.objects.create(
            company=self.co_b,
            employee_id='B001',
            first_name='Bob',
            last_name='Beta',
            date_hired=datetime.date(2024, 1, 1),
            status='active',
            biometric_user_id='42',
        )

    def _now(self):
        return timezone.now()

    # -- BiometricLog belongs to company --

    def test_log_belongs_to_company(self):
        log = BiometricLog.objects.create(
            company=self.co_a,
            biometric_user_id='42',
            punch_time=self._now(),
        )
        self.assertEqual(log.company, self.co_a)

    # -- match_employee_for_biometric_log --

    def test_match_returns_correct_employee_for_company(self):
        emp = match_employee_for_biometric_log(self.co_a, '42')
        self.assertEqual(emp, self.emp_a)

    def test_match_uses_company_scope_not_global(self):
        # Same biometric_user_id '42' exists in both companies — must not cross-match.
        emp_from_a = match_employee_for_biometric_log(self.co_a, '42')
        emp_from_b = match_employee_for_biometric_log(self.co_b, '42')
        self.assertEqual(emp_from_a, self.emp_a)
        self.assertEqual(emp_from_b, self.emp_b)
        self.assertNotEqual(emp_from_a, emp_from_b)

    def test_match_returns_none_for_unknown_id(self):
        emp = match_employee_for_biometric_log(self.co_a, '9999')
        self.assertIsNone(emp)

    def test_match_returns_none_for_empty_id(self):
        emp = match_employee_for_biometric_log(self.co_a, '')
        self.assertIsNone(emp)

    # -- create_biometric_log --

    def test_create_log_stores_raw_payload(self):
        payload = {'uid': '42', 'timestamp': '2026-05-27T08:00:00'}
        log = create_biometric_log(
            company=self.co_a,
            punch_time=self._now(),
            biometric_user_id='42',
            device=self.dev_a,
            punch_type='check_in',
            raw_payload=payload,
        )
        self.assertEqual(log.raw_payload, payload)
        self.assertEqual(log.punch_type, 'check_in')
        self.assertEqual(log.device, self.dev_a)

    def test_create_log_matches_employee_when_found(self):
        log = create_biometric_log(
            company=self.co_a,
            punch_time=self._now(),
            biometric_user_id='42',
        )
        self.assertEqual(log.employee, self.emp_a)
        self.assertFalse(log.processed)

    def test_create_log_does_not_crash_when_employee_not_found(self):
        log = create_biometric_log(
            company=self.co_a,
            punch_time=self._now(),
            biometric_user_id='UNKNOWN_ID',
        )
        self.assertIsNone(log.employee)
        self.assertEqual(log.biometric_user_id, 'UNKNOWN_ID')

    def test_create_log_defaults_raw_payload_to_empty_dict(self):
        log = create_biometric_log(
            company=self.co_a,
            punch_time=self._now(),
            biometric_user_id='42',
        )
        self.assertEqual(log.raw_payload, {})

    # -- mark_log_processed --

    def test_mark_log_processed_sets_flag_and_timestamp(self):
        log = create_biometric_log(
            company=self.co_a, punch_time=self._now(), biometric_user_id='42'
        )
        self.assertFalse(log.processed)
        self.assertIsNone(log.processed_at)
        mark_log_processed(log)
        log.refresh_from_db()
        self.assertTrue(log.processed)
        self.assertIsNotNone(log.processed_at)

    def test_mark_log_processed_with_error_message(self):
        log = create_biometric_log(
            company=self.co_a, punch_time=self._now(), biometric_user_id='42'
        )
        mark_log_processed(log, error_message='Duplicate record skipped')
        log.refresh_from_db()
        self.assertTrue(log.processed)
        self.assertIn('Duplicate', log.error_message)


# ── AttendanceLocation model tests ────────────────────────────────────────────

class AttendanceLocationModelTests(TestCase):
    def setUp(self):
        self.company = _make_company()

    def _make_location(self, **kwargs):
        defaults = dict(company=self.company, name='Main Office', ip_address='112.198.10.5')
        defaults.update(kwargs)
        return AttendanceLocation.objects.create(**defaults)

    def test_create_location_with_exact_ip(self):
        loc = self._make_location(ip_address='112.198.10.5')
        self.assertEqual(loc.company, self.company)
        self.assertEqual(loc.ip_address, '112.198.10.5')
        self.assertTrue(loc.is_active)

    def test_create_location_with_cidr(self):
        loc = self._make_location(ip_address=None, cidr_range='192.168.1.0/24')
        self.assertEqual(loc.cidr_range, '192.168.1.0/24')
        self.assertIsNone(loc.ip_address)

    def test_str_shows_company_and_name(self):
        loc = self._make_location(name='Cebu Branch')
        self.assertIn('Test Co', str(loc))
        self.assertIn('Cebu Branch', str(loc))

    def test_clean_raises_if_neither_ip_nor_cidr(self):
        from django.core.exceptions import ValidationError
        loc = AttendanceLocation(company=self.company, name='Bad', ip_address=None, cidr_range='')
        with self.assertRaises(ValidationError):
            loc.clean()

    def test_clean_raises_on_invalid_cidr(self):
        from django.core.exceptions import ValidationError
        loc = AttendanceLocation(company=self.company, name='Bad', cidr_range='not-a-cidr')
        with self.assertRaises(ValidationError):
            loc.clean()

    def test_inactive_location_is_excluded_from_active_filter(self):
        self._make_location(is_active=False, name='Old Office')
        active = AttendanceLocation.objects.filter(company=self.company, is_active=True)
        self.assertEqual(active.count(), 0)


# ── ip_matches_location and find_matching_attendance_location tests ───────────

class IPMatchingTests(TestCase):
    def setUp(self):
        self.co_a = _make_company()
        self.co_b = Company.objects.create(name='Company B')

    def _make_location(self, company, ip=None, cidr=None, is_active=True, name='Office'):
        return AttendanceLocation.objects.create(
            company=company,
            name=name,
            ip_address=ip,
            cidr_range=cidr or '',
            is_active=is_active,
        )

    def _make_emp(self, company):
        return _make_employee(company)

    # ip_matches_location — exact IP
    def test_exact_ip_match(self):
        loc = self._make_location(self.co_a, ip='1.2.3.4')
        self.assertTrue(ip_matches_location('1.2.3.4', loc))

    def test_exact_ip_no_match(self):
        loc = self._make_location(self.co_a, ip='1.2.3.4')
        self.assertFalse(ip_matches_location('1.2.3.5', loc))

    # ip_matches_location — CIDR
    def test_cidr_match_inside_range(self):
        loc = self._make_location(self.co_a, ip=None, cidr='192.168.1.0/24')
        self.assertTrue(ip_matches_location('192.168.1.100', loc))

    def test_cidr_no_match_outside_range(self):
        loc = self._make_location(self.co_a, ip=None, cidr='192.168.1.0/24')
        self.assertFalse(ip_matches_location('192.168.2.1', loc))

    def test_invalid_ip_returns_false(self):
        loc = self._make_location(self.co_a, ip='1.2.3.4')
        self.assertFalse(ip_matches_location('not-an-ip', loc))

    def test_empty_ip_returns_false(self):
        loc = self._make_location(self.co_a, ip='1.2.3.4')
        self.assertFalse(ip_matches_location('', loc))

    # find_matching_attendance_location — company scoping
    def test_inactive_location_not_matched(self):
        emp = self._make_emp(self.co_a)
        self._make_location(self.co_a, ip='5.5.5.5', is_active=False)
        result = find_matching_attendance_location(emp, '5.5.5.5')
        self.assertIsNone(result)

    def test_employee_company_a_cannot_use_company_b_location(self):
        emp_a = self._make_emp(self.co_a)
        # Register the same IP under Company B only
        self._make_location(self.co_b, ip='9.9.9.9')
        result = find_matching_attendance_location(emp_a, '9.9.9.9')
        self.assertIsNone(result)

    def test_find_returns_matching_location(self):
        emp = self._make_emp(self.co_a)
        loc = self._make_location(self.co_a, ip='7.7.7.7')
        result = find_matching_attendance_location(emp, '7.7.7.7')
        self.assertEqual(result, loc)

    def test_find_returns_none_when_no_match(self):
        emp = self._make_emp(self.co_a)
        self._make_location(self.co_a, ip='7.7.7.7')
        result = find_matching_attendance_location(emp, '8.8.8.8')
        self.assertIsNone(result)


# ── Portal view tests ─────────────────────────────────────────────────────────

class AttendancePortalViewTests(TestCase):
    """
    Tests for /attendance/portal/ — IP-locked employee attendance portal.
    All tests use 127.0.0.1 as REMOTE_ADDR (Django test client default).
    Phase 2: employee must also have a schedule today for the portal to allow.
    """

    def setUp(self):
        self.company = _make_company()
        self.company.attendance_log_page_opened_events = True
        self.company.save(update_fields=['attendance_log_page_opened_events'])
        # All-week schedule so tests pass regardless of what day they run.
        self.schedule = _make_schedule(
            self.company,
            work_saturday=True,
            work_sunday=True,
        )
        self.employee = _make_employee(self.company, self.schedule)

        # User linked to employee via OneToOneField
        self.user = User.objects.create_user('portaluser', password='pass')
        self.employee.user = self.user
        self.employee.save(update_fields=['user'])

        self.portal_url = reverse('attendance:attendance_portal')

    def _make_location(self, ip='127.0.0.1', is_active=True, require_selfie=False, require_gps=False):
        return AttendanceLocation.objects.create(
            company=self.company,
            name='Test Network',
            ip_address=ip,
            is_active=is_active,
            require_selfie=require_selfie,
            require_gps=require_gps,
        )

    def _selfie_payload(self):
        image_buffer = io.BytesIO()
        Image.new('RGB', (2, 2), color=(35, 35, 35)).save(image_buffer, format='JPEG')
        encoded = base64.b64encode(image_buffer.getvalue()).decode('ascii')
        return f'data:image/jpeg;base64,{encoded}'

    def test_portal_requires_login(self):
        resp = self.client.get(self.portal_url)
        self.assertRedirects(resp, f'/accounts/login/?next={self.portal_url}')

    def test_portal_blocks_unapproved_ip(self):
        # No location registered — 127.0.0.1 will not match anything
        self.client.login(username='portaluser', password='pass')
        resp = self.client.get(self.portal_url)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.context['allowed'])
        self.assertIn('127.0.0.1', resp.context['ip'])

    def test_portal_blocks_page_open_creates_log(self):
        self.client.login(username='portaluser', password='pass')
        self.client.get(self.portal_url)
        log = AttendancePortalLog.objects.filter(employee=self.employee, action='page_open').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.status, 'blocked')

    def test_portal_allows_approved_ip(self):
        self._make_location(ip='127.0.0.1')
        self.client.login(username='portaluser', password='pass')
        resp = self.client.get(self.portal_url)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context['allowed'])

    def test_portal_allowed_page_open_creates_allowed_log(self):
        self._make_location(ip='127.0.0.1')
        self.client.login(username='portaluser', password='pass')
        self.client.get(self.portal_url)
        log = AttendancePortalLog.objects.filter(employee=self.employee, action='page_open').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.status, 'allowed')

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_time_in_creates_attendance_record(self, _mock):
        self._make_location(ip='127.0.0.1')
        self.client.login(username='portaluser', password='pass')
        self.client.post(self.portal_url, {'action': 'time_in'})
        record = AttendanceRecord.objects.filter(employee=self.employee).first()
        self.assertIsNotNone(record)
        self.assertIsNotNone(record.time_in)
        self.assertEqual(record.source, 'portal')

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_time_in_blocked_without_approved_location(self, _mock):
        # No location registered — 127.0.0.1 will not match anything
        self.client.login(username='portaluser', password='pass')
        self.client.post(self.portal_url, {'action': 'time_in'})
        self.assertEqual(AttendanceRecord.objects.filter(employee=self.employee).count(), 0)

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_time_in_creates_portal_log(self, _mock):
        self._make_location(ip='127.0.0.1')
        self.client.login(username='portaluser', password='pass')
        self.client.post(self.portal_url, {'action': 'time_in'})
        log = AttendancePortalLog.objects.filter(
            employee=self.employee, action='time_in'
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.status, 'success')

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_time_in_blocked_when_selfie_required_but_missing(self, _mock):
        self._make_location(ip='127.0.0.1', require_selfie=True)
        self.client.login(username='portaluser', password='pass')
        self.client.post(self.portal_url, {'action': 'time_in'})
        self.assertEqual(AttendanceRecord.objects.filter(employee=self.employee).count(), 0)
        log = AttendancePortalLog.objects.filter(employee=self.employee, action='time_in').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.status, 'blocked')
        self.assertIn('selfie', log.blocked_reason.lower())

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_time_in_blocked_when_gps_required_but_missing(self, _mock):
        self._make_location(ip='127.0.0.1', require_gps=True)
        self.client.login(username='portaluser', password='pass')
        self.client.post(self.portal_url, {'action': 'time_in'})
        self.assertEqual(AttendanceRecord.objects.filter(employee=self.employee).count(), 0)
        log = AttendancePortalLog.objects.filter(employee=self.employee, action='time_in').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.status, 'blocked')
        self.assertIn('gps', log.blocked_reason.lower())

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_time_in_works_with_required_selfie_and_gps(self, _mock):
        self._make_location(ip='127.0.0.1', require_selfie=True, require_gps=True)
        self.client.login(username='portaluser', password='pass')
        self.client.post(self.portal_url, {
            'action': 'time_in',
            'selfie_data': self._selfie_payload(),
            'gps_latitude': '14.609100',
            'gps_longitude': '121.022300',
            'gps_accuracy': '10.20',
        })
        record = AttendanceRecord.objects.filter(employee=self.employee).first()
        self.assertIsNotNone(record)
        log = AttendancePortalLog.objects.filter(employee=self.employee, action='time_in').first()
        self.assertEqual(log.status, 'success')
        self.assertIsNotNone(log.selfie_image)
        self.assertEqual(str(log.gps_latitude), '14.609100')
        self.assertEqual(str(log.gps_longitude), '121.022300')

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_time_out_blocked_when_required_selfie_or_gps_missing(self, _mock):
        self._make_location(ip='127.0.0.1', require_selfie=True, require_gps=True)
        today = datetime.date.today()
        AttendanceRecord.objects.create(
            company=self.company,
            employee=self.employee,
            date=today,
            time_in=datetime.time(8, 0),
            status='present',
            source='portal',
        )
        self.client.login(username='portaluser', password='pass')
        self.client.post(self.portal_url, {'action': 'time_out'})
        record = AttendanceRecord.objects.get(employee=self.employee, date=today)
        self.assertIsNone(record.time_out)
        log = AttendancePortalLog.objects.filter(employee=self.employee, action='time_out').first()
        self.assertEqual(log.status, 'blocked')

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_time_out_works_with_required_selfie_and_gps(self, _mock):
        self._make_location(ip='127.0.0.1', require_selfie=True, require_gps=True)
        today = datetime.date.today()
        record = AttendanceRecord.objects.create(
            company=self.company,
            employee=self.employee,
            date=today,
            time_in=datetime.time(8, 0),
            status='present',
            source='portal',
        )
        self.client.login(username='portaluser', password='pass')
        self.client.post(self.portal_url, {
            'action': 'time_out',
            'selfie_data': self._selfie_payload(),
            'gps_latitude': '14.609100',
            'gps_longitude': '121.022300',
            'gps_accuracy': '8.50',
        })
        record.refresh_from_db()
        self.assertIsNotNone(record.time_out)
        log = AttendancePortalLog.objects.filter(employee=self.employee, action='time_out').first()
        self.assertEqual(log.status, 'success')
        self.assertIsNotNone(log.selfie_image)

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_portal_time_in_always_applies_to_logged_in_employee_only(self, _mock):
        self._make_location(ip='127.0.0.1')
        other_employee = _make_employee(self.company, self.schedule)
        self.client.login(username='portaluser', password='pass')
        self.client.post(self.portal_url, {'action': 'time_in', 'employee_id': other_employee.pk})
        self.assertEqual(
            AttendanceRecord.objects.filter(employee=other_employee, date=datetime.date.today()).count(),
            0,
        )
        self.assertEqual(
            AttendanceRecord.objects.filter(employee=self.employee, date=datetime.date.today()).count(),
            1,
        )

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_time_out_updates_record(self, _mock):
        self._make_location(ip='127.0.0.1')
        today = datetime.date.today()
        record = AttendanceRecord.objects.create(
            company=self.company,
            employee=self.employee,
            date=today,
            time_in=datetime.time(8, 0),
            status='present',
            source='portal',
        )
        self.client.login(username='portaluser', password='pass')
        self.client.post(self.portal_url, {'action': 'time_out'})
        record.refresh_from_db()
        self.assertIsNotNone(record.time_out)

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_double_time_in_prevented(self, _mock):
        self._make_location(ip='127.0.0.1')
        today = datetime.date.today()
        AttendanceRecord.objects.create(
            company=self.company,
            employee=self.employee,
            date=today,
            time_in=datetime.time(8, 0),
            status='present',
            source='portal',
        )
        self.client.login(username='portaluser', password='pass')
        self.client.post(self.portal_url, {'action': 'time_in'})
        # Still only one record
        self.assertEqual(
            AttendanceRecord.objects.filter(employee=self.employee, date=today).count(), 1
        )


# ── Location CRUD access control tests ───────────────────────────────────────

class AttendanceLocationAccessTests(TestCase):
    """
    Superuser can manage all locations; normal user without can_manage_attendance
    is denied (module_access_required decorator redirects to 403 or login).
    """

    def setUp(self):
        self.co_a = _make_company()
        self.co_b = Company.objects.create(name='Company B')
        self.loc_a = AttendanceLocation.objects.create(
            company=self.co_a, name='Office A', ip_address='1.1.1.1'
        )

        self.superuser = User.objects.create_superuser('su', password='pass')

        # Normal user with no module permissions
        self.plain_user = User.objects.create_user('plain', password='pass')

    def test_superuser_can_list_locations(self):
        self.client.login(username='su', password='pass')
        resp = self.client.get(reverse('attendance:location_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Office A')

    def test_plain_user_cannot_list_locations(self):
        self.client.login(username='plain', password='pass')
        resp = self.client.get(reverse('attendance:location_list'))
        # module_access_required redirects to 403 or login
        self.assertIn(resp.status_code, [302, 403])

    def test_superuser_can_reach_add_location(self):
        self.client.login(username='su', password='pass')
        resp = self.client.get(reverse('attendance:location_add'))
        self.assertEqual(resp.status_code, 200)

    def test_superuser_can_delete_location(self):
        self.client.login(username='su', password='pass')
        resp = self.client.get(reverse('attendance:location_delete', args=[self.loc_a.pk]))
        self.assertEqual(resp.status_code, 200)


# ===========================================================================
# Phase 2 — Shift Roster and Date-Based Attendance Tests
# ===========================================================================

from .models import EmployeeDailySchedule, ShiftTemplate
from .schedule_services import resolve_expected_shift


def _make_shift(company, name='Day Shift', start=None, end=None, **kwargs):
    return ShiftTemplate.objects.create(
        company=company,
        name=name,
        start_time=start or datetime.time(8, 0),
        end_time=end or datetime.time(17, 0),
        **kwargs,
    )


def _make_daily_schedule(company, employee, date, shift=None, **kwargs):
    return EmployeeDailySchedule.objects.create(
        company=company,
        employee=employee,
        schedule_date=date,
        shift_template=shift,
        **kwargs,
    )


class ShiftTemplateModelTests(TestCase):
    """Test 1 — ShiftTemplate creation and constraints."""

    def setUp(self):
        self.company = _make_company()

    def test_shift_template_creation(self):
        shift = _make_shift(
            self.company,
            name='Morning',
            start=datetime.time(6, 0),
            end=datetime.time(14, 0),
            break_minutes=30,
            grace_minutes=5,
        )
        self.assertEqual(shift.company, self.company)
        self.assertEqual(shift.start_time, datetime.time(6, 0))
        self.assertEqual(shift.end_time, datetime.time(14, 0))
        self.assertEqual(shift.break_minutes, 30)
        self.assertTrue(shift.is_active)
        self.assertIn('Morning', str(shift))

    def test_shift_template_clean_raises_when_end_before_start_not_overnight(self):
        from django.core.exceptions import ValidationError
        shift = ShiftTemplate(
            company=self.company,
            name='Bad',
            start_time=datetime.time(17, 0),
            end_time=datetime.time(8, 0),
            is_overnight=False,
        )
        with self.assertRaises(ValidationError):
            shift.clean()

    def test_shift_template_overnight_does_not_raise(self):
        shift = ShiftTemplate(
            company=self.company,
            name='Night',
            start_time=datetime.time(22, 0),
            end_time=datetime.time(6, 0),
            is_overnight=True,
        )
        shift.clean()  # must not raise


class EmployeeDailyScheduleUniqueTests(TestCase):
    """Test 2 — EmployeeDailySchedule unique_together constraint."""

    def setUp(self):
        self.company = _make_company()
        self.employee = _make_employee(self.company)
        self.shift = _make_shift(self.company)
        self.date = datetime.date(2026, 6, 1)

    def test_unique_schedule_per_employee_per_date(self):
        from django.db import IntegrityError
        _make_daily_schedule(self.company, self.employee, self.date, self.shift)
        with self.assertRaises(IntegrityError):
            _make_daily_schedule(self.company, self.employee, self.date, self.shift)

    def test_same_employee_different_dates_allowed(self):
        _make_daily_schedule(self.company, self.employee, self.date, self.shift)
        ds2 = _make_daily_schedule(
            self.company, self.employee,
            self.date + datetime.timedelta(days=1), self.shift,
        )
        self.assertIsNotNone(ds2.pk)


class ScheduleResolverTests(TestCase):
    """Tests 3 & 4 — schedule resolver priority and weekday detection."""

    def setUp(self):
        self.company = _make_company()

    def test_daily_schedule_overrides_work_schedule(self):
        """Test 3: date-specific EmployeeDailySchedule overrides WorkSchedule."""
        ws = _make_schedule(
            self.company,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(18, 0),
        )
        emp = _make_employee(self.company, ws)
        date = datetime.date(2026, 6, 1)  # Monday

        # Without a daily schedule the WorkSchedule applies
        shift_from_ws = resolve_expected_shift(emp, date)
        self.assertEqual(shift_from_ws['source'], 'work_schedule')
        self.assertEqual(shift_from_ws['start_time'], datetime.time(9, 0))

        # Add a daily schedule with different times
        template = _make_shift(
            self.company,
            start=datetime.time(6, 0),
            end=datetime.time(14, 0),
        )
        _make_daily_schedule(self.company, emp, date, template)

        shift_from_daily = resolve_expected_shift(emp, date)
        self.assertEqual(shift_from_daily['source'], 'daily_schedule')
        self.assertEqual(shift_from_daily['start_time'], datetime.time(6, 0))
        self.assertEqual(shift_from_daily['end_time'], datetime.time(14, 0))

    def test_rotating_weekly_schedule_workday_and_rest_day(self):
        """Test 4: WorkSchedule weekday flags give correct scheduled / rest-day results."""
        ws = _make_schedule(
            self.company,
            work_saturday=False,
            work_sunday=False,
        )
        emp = _make_employee(self.company, ws)

        monday = datetime.date(2026, 6, 1)    # weekday() == 0
        saturday = datetime.date(2026, 6, 6)  # weekday() == 5

        mon_shift = resolve_expected_shift(emp, monday)
        self.assertTrue(mon_shift['scheduled'])
        self.assertEqual(mon_shift['source'], 'work_schedule')
        self.assertEqual(mon_shift['start_time'], ws.start_time)
        self.assertEqual(mon_shift['end_time'], ws.end_time)

        sat_shift = resolve_expected_shift(emp, saturday)
        self.assertFalse(sat_shift['scheduled'])
        self.assertTrue(sat_shift['is_rest_day'])

    def test_no_schedule_returns_unscheduled(self):
        emp = _make_employee(self.company)  # no work_schedule
        date = datetime.date(2026, 6, 1)
        shift = resolve_expected_shift(emp, date)
        self.assertFalse(shift['scheduled'])
        self.assertFalse(shift['is_rest_day'])
        self.assertEqual(shift['source'], 'none')


class DailyScheduleComputeTests(TestCase):
    """Tests 5–8 — compute_attendance uses the resolved daily schedule."""

    def setUp(self):
        self.company = _make_company()
        self.employee = _make_employee(self.company)
        # Use a fixed Monday for all date-specific tests
        self.date = datetime.date(2026, 6, 1)

    def _assign_shift(self, start, end, break_minutes=60, grace_minutes=10,
                      overtime_after_minutes=0, is_overnight=False):
        shift = _make_shift(
            self.company,
            start=start,
            end=end,
            break_minutes=break_minutes,
            grace_minutes=grace_minutes,
            overtime_after_minutes=overtime_after_minutes,
            is_overnight=is_overnight,
        )
        _make_daily_schedule(self.company, self.employee, self.date, shift)
        return shift

    def _record(self, time_in=None, time_out=None, break_minutes=60):
        return AttendanceRecord.objects.create(
            company=self.company,
            employee=self.employee,
            date=self.date,
            time_in=time_in,
            time_out=time_out,
            break_minutes=break_minutes,
            status='present',
        )

    def test_late_calculation_uses_daily_schedule(self):
        """Test 5: late_minutes uses the assigned ShiftTemplate grace period."""
        self._assign_shift(
            start=datetime.time(8, 0),
            end=datetime.time(17, 0),
            break_minutes=60,
            grace_minutes=10,
        )
        record = self._record(
            time_in=datetime.time(8, 15),   # 5 minutes past grace cutoff (8:10)
            time_out=datetime.time(17, 0),
            break_minutes=60,
        )
        compute_attendance(record)
        record.refresh_from_db()
        self.assertEqual(record.late_minutes, 5)

    def test_undertime_calculation_uses_daily_schedule(self):
        """Test 6: undertime uses assigned shift (expected = sched_end - sched_start - break)."""
        self._assign_shift(
            start=datetime.time(8, 0),
            end=datetime.time(17, 0),
            break_minutes=60,
        )
        # Clock out at 13:00 → 4 h net work vs 8 h expected → undertime
        record = self._record(
            time_in=datetime.time(8, 0),
            time_out=datetime.time(13, 0),
            break_minutes=60,
        )
        compute_attendance(record)
        record.refresh_from_db()
        self.assertEqual(record.computed_status, 'undertime')
        self.assertGreater(record.undertime_minutes, 0)

    def test_overtime_calculation_uses_daily_schedule(self):
        """Test 7: overtime starts at sched_end + overtime_after_minutes of the template."""
        self._assign_shift(
            start=datetime.time(8, 0),
            end=datetime.time(17, 0),
            break_minutes=60,
            overtime_after_minutes=0,
        )
        # 2 hours overtime
        record = self._record(
            time_in=datetime.time(8, 0),
            time_out=datetime.time(19, 0),
            break_minutes=60,
        )
        compute_attendance(record)
        record.refresh_from_db()
        self.assertEqual(record.overtime_minutes, 120)
        self.assertEqual(record.computed_status, 'overtime')

    def test_overnight_shift_computes_correctly(self):
        """Test 8: overnight shift (10 PM – 6 AM) does not produce negative work time."""
        self._assign_shift(
            start=datetime.time(22, 0),
            end=datetime.time(6, 0),
            break_minutes=0,
            grace_minutes=0,
            is_overnight=True,
        )
        record = self._record(
            time_in=datetime.time(22, 0),
            time_out=datetime.time(6, 0),   # next day 6 AM
            break_minutes=0,
        )
        compute_attendance(record)
        record.refresh_from_db()
        # 22:00 → 06:00 = 8 h
        self.assertEqual(record.total_work_minutes, 480)
        self.assertEqual(record.computed_status, 'present')


class PortalScheduleGatingTests(TestCase):
    """Tests 9 & 10 — portal schedule gating combined with IP check."""

    def setUp(self):
        self.company = _make_company()
        self.portal_url = reverse('attendance:attendance_portal')

    def _make_user_with_employee(self, schedule=None):
        emp = _make_employee(self.company, schedule)
        user = User.objects.create_user(f'puser_{emp.pk}', password='pass')
        emp.user = user
        emp.save(update_fields=['user'])
        return user, emp

    def _make_location(self, ip='127.0.0.1'):
        return AttendanceLocation.objects.create(
            company=self.company, name='Office', ip_address=ip
        )

    def test_portal_blocks_if_no_schedule_today_even_with_approved_ip(self):
        """Test 9: schedule_allowed=False even when IP matches."""
        user, _emp = self._make_user_with_employee(schedule=None)  # no schedule
        self._make_location(ip='127.0.0.1')
        self.client.login(username=user.username, password='pass')
        resp = self.client.get(self.portal_url)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.context['allowed'])
        self.assertFalse(resp.context['schedule_allowed'])

    def test_portal_allows_if_schedule_and_ip_both_approved(self):
        """Test 10: allowed=True when both IP and schedule pass."""
        schedule = _make_schedule(
            self.company,
            work_saturday=True,
            work_sunday=True,
        )
        user, _emp = self._make_user_with_employee(schedule=schedule)
        self._make_location(ip='127.0.0.1')
        self.client.login(username=user.username, password='pass')
        resp = self.client.get(self.portal_url)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context['allowed'])
        self.assertTrue(resp.context['ip_allowed'])
        self.assertTrue(resp.context['schedule_allowed'])


_TEST_DAY_FIELDS = [
    'work_monday', 'work_tuesday', 'work_wednesday', 'work_thursday',
    'work_friday', 'work_saturday', 'work_sunday',
]


class PotentialAbsencesTodayTests(TestCase):
    """Test 11 — _potential_absences_today respects schedule priority correctly."""

    def setUp(self):
        self.company = _make_company()
        self.today = datetime.date.today()
        self.day_field = _TEST_DAY_FIELDS[self.today.weekday()]

    def test_employee_with_daily_schedule_included(self):
        """Employee with EmployeeDailySchedule (non-rest) counts as scheduled today."""
        from attendance.views import _potential_absences_today
        emp = _make_employee(self.company)
        shift = _make_shift(self.company)
        _make_daily_schedule(self.company, emp, self.today, shift)

        absent = _potential_absences_today(company=self.company)
        self.assertIn(emp, list(absent))

    def test_employee_with_rest_day_schedule_excluded(self):
        """Employee whose daily schedule is rest_day must NOT appear in absences."""
        from attendance.views import _potential_absences_today
        emp = _make_employee(self.company)
        _make_daily_schedule(self.company, emp, self.today, is_rest_day=True)

        absent = _potential_absences_today(company=self.company)
        self.assertNotIn(emp, list(absent))

    def test_employee_without_schedule_excluded(self):
        """Employee with no schedule (daily or work) must not appear."""
        from attendance.views import _potential_absences_today
        emp = _make_employee(self.company)  # no schedule

        absent = _potential_absences_today(company=self.company)
        self.assertNotIn(emp, list(absent))

    def test_daily_schedule_overrides_work_schedule_rest_day(self):
        """
        Employee's WorkSchedule says today is a workday, but a daily schedule
        marks today as rest_day — they must NOT appear in potential absences.
        """
        from attendance.views import _potential_absences_today
        ws = WorkSchedule.objects.create(
            company=self.company,
            name='All Week',
            start_time=datetime.time(8, 0),
            end_time=datetime.time(17, 0),
            work_monday=True, work_tuesday=True, work_wednesday=True,
            work_thursday=True, work_friday=True,
            work_saturday=True, work_sunday=True,
        )
        emp = _make_employee(self.company, ws)
        # Override today with a rest-day daily schedule
        _make_daily_schedule(self.company, emp, self.today, is_rest_day=True)

        absent = _potential_absences_today(company=self.company)
        self.assertNotIn(emp, list(absent))


class ScheduleCrossCompanyAccessTests(TestCase):
    """Test 12 — cross-company user cannot manage another company's schedules."""

    def setUp(self):
        self.co_a = _make_company()
        self.co_b = Company.objects.create(name='Company B')

        # Shift and schedule belonging to Company A
        self.shift_a = _make_shift(self.co_a, name='Shift A')

        # Superuser (can see everything)
        self.superuser = User.objects.create_superuser('su_sched', password='pass')

        # User assigned only to Company A with attendance module access
        self.user_a = User.objects.create_user('user_sched_a', password='pass')
        from accounts.models import UserCompanyAccess, UserProfile
        UserCompanyAccess.objects.create(
            user=self.user_a, company=self.co_a, role='hr_admin', is_active=True
        )
        UserProfile.objects.create(
            user=self.user_a, role='hr_admin',
            is_active_stafforyx=True,
            can_manage_attendance=True,
        )

    def test_company_a_user_sees_shift_list(self):
        self.client.login(username='user_sched_a', password='pass')
        resp = self.client.get(reverse('attendance:shift_list'))
        self.assertEqual(resp.status_code, 200)

    def test_company_a_user_cannot_reach_company_b_shift_edit(self):
        shift_b = _make_shift(self.co_b, name='Shift B')
        self.client.login(username='user_sched_a', password='pass')
        resp = self.client.get(reverse('attendance:shift_edit', args=[shift_b.pk]))
        # View must return 403/404, not let the user edit Company B's shift
        self.assertIn(resp.status_code, [403, 404])

    def test_employee_schedule_list_accessible_to_hr(self):
        self.client.login(username='user_sched_a', password='pass')
        resp = self.client.get(reverse('attendance:employee_schedule_list'))
        self.assertEqual(resp.status_code, 200)

    def test_plain_user_cannot_access_shift_list(self):
        plain = User.objects.create_user('plain_sched', password='pass')
        self.client.login(username='plain_sched', password='pass')
        resp = self.client.get(reverse('attendance:shift_list'))
        self.assertIn(resp.status_code, [302, 403])


class FlexibleScheduleAttendanceTests(TestCase):
    """Flexible employees: no late from start; under/overtime vs required_daily_hours."""

    def setUp(self):
        self.company = _make_company()
        # Mon-Fri schedule used only for workday/rest-day resolution.
        self.schedule = _make_schedule(
            self.company,
            start_time=datetime.time(8, 0),
            end_time=datetime.time(17, 0),
        )

    def _flex_employee(self, required_hours='8.00', break_minutes=60):
        emp = _make_employee(self.company, self.schedule)
        emp.flexible_schedule_enabled = True
        emp.required_daily_hours = Decimal(required_hours)
        emp.default_break_minutes = break_minutes
        emp.save(update_fields=[
            'flexible_schedule_enabled', 'required_daily_hours', 'default_break_minutes',
        ])
        return emp

    def test_flexible_not_late_when_starting_later(self):
        emp = self._flex_employee()
        # Starts 10:00, works to 19:00, 60 min break = 8.0h worked.
        rec = _make_record(
            emp, time_in=datetime.time(10, 0), time_out=datetime.time(19, 0),
        )
        compute_attendance(rec)
        rec.refresh_from_db()
        self.assertEqual(rec.late_minutes, 0)
        self.assertEqual(rec.undertime_minutes, 0)
        self.assertEqual(rec.overtime_minutes, 0)
        self.assertEqual(rec.computed_status, 'present')

    def test_flexible_undertime_when_below_required(self):
        emp = self._flex_employee()
        # 09:00-15:00, 60 min break = 5.0h worked → 3h (180 min) undertime.
        rec = _make_record(
            emp, time_in=datetime.time(9, 0), time_out=datetime.time(15, 0),
        )
        compute_attendance(rec)
        rec.refresh_from_db()
        self.assertEqual(rec.late_minutes, 0)
        self.assertEqual(rec.undertime_minutes, 180)
        self.assertEqual(rec.overtime_minutes, 0)
        self.assertEqual(rec.computed_status, 'undertime')

    def test_flexible_overtime_when_above_required(self):
        emp = self._flex_employee()
        # 08:00-19:00, 60 min break = 10.0h worked → 2h (120 min) overtime.
        rec = _make_record(
            emp, time_in=datetime.time(8, 0), time_out=datetime.time(19, 0),
        )
        compute_attendance(rec)
        rec.refresh_from_db()
        self.assertEqual(rec.overtime_minutes, 120)
        self.assertEqual(rec.undertime_minutes, 0)
        self.assertEqual(rec.computed_status, 'overtime')


class FixedShiftRegressionTests(TestCase):
    """Guards: fixed-shift behavior must be unchanged by the flexible branch."""

    def setUp(self):
        self.company = _make_company()
        # 2 PM - 10 PM shift, grace 15, break 60.
        self.schedule = _make_schedule(
            self.company,
            start_time=datetime.time(14, 0),
            end_time=datetime.time(22, 0),
        )

    def test_fixed_shift_late_undertime_overtime(self):
        emp = _make_employee(self.company, self.schedule)
        self.assertFalse(emp.flexible_schedule_enabled)
        # Clock in 14:30 (15 min late after grace), out 22:00.
        rec = _make_record(
            emp, time_in=datetime.time(14, 30), time_out=datetime.time(22, 0),
        )
        compute_attendance(rec)
        rec.refresh_from_db()
        self.assertEqual(rec.late_minutes, 15)
        # Expected = 8h shift - 1h break = 7h; worked 22:00-14:30-60 = 6.5h → 30 min undertime.
        self.assertEqual(rec.undertime_minutes, 30)
        self.assertEqual(rec.overtime_minutes, 0)
        # Fixed-shift status precedence (UNCHANGED): undertime dominates late when
        # both are present (see ComputeAttendanceTotalHoursTests.test_after_grace_late_minutes_counted).
        self.assertEqual(rec.computed_status, 'undertime')

    def test_fixed_shift_overtime(self):
        emp = _make_employee(self.company, self.schedule)
        # 14:00 - 23:30: worked 9.5h - 1h break = 8.5h; OT after 22:00 = 90 min.
        rec = _make_record(
            emp, time_in=datetime.time(14, 0), time_out=datetime.time(23, 30),
        )
        compute_attendance(rec)
        rec.refresh_from_db()
        self.assertEqual(rec.overtime_minutes, 90)
        self.assertEqual(rec.computed_status, 'overtime')
