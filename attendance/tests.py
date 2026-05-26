import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from companies.models import Company
from employees.models import Employee
from .models import AttendanceRecord, WorkSchedule
from .services import compute_attendance


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


def _make_record(employee, date=None, time_in=None, time_out=None, break_minutes=0):
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
