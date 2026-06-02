import datetime
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from companies.models import Company
from employees.models import Employee
from .models import OvertimeRequest
from .services import build_overtime_approval_index, payable_overtime_minutes

_DATE = datetime.date(2026, 5, 26)


def _company():
    return Company.objects.create(name='OT Co')


_counter = 0


def _employee(company, policy='not_allowed'):
    global _counter
    _counter += 1
    return Employee.objects.create(
        company=company,
        employee_id=f'OT{_counter:03d}',
        first_name='Over',
        last_name='Time',
        date_hired=datetime.date(2024, 1, 1),
        status='active',
        overtime_policy=policy,
    )


class PayableOvertimeHelperTests(TestCase):
    def setUp(self):
        self.company = _company()

    def _index(self, employees):
        return build_overtime_approval_index(self.company, employees, _DATE, _DATE)

    def test_automatic_pays_detected(self):
        emp = _employee(self.company, 'automatic')
        idx = self._index([emp])
        self.assertEqual(payable_overtime_minutes(emp, _DATE, 120, idx), 120)

    def test_request_required_zero_without_approval(self):
        emp = _employee(self.company, 'request_required')
        idx = self._index([emp])
        self.assertEqual(payable_overtime_minutes(emp, _DATE, 120, idx), 0)

    def test_request_required_pays_min_detected_approved(self):
        emp = _employee(self.company, 'request_required')
        OvertimeRequest.objects.create(
            company=self.company, employee=emp, date=_DATE,
            requested_hours=Decimal('2.00'), approved_hours=Decimal('1.50'),
            status='approved', source='employee',
        )
        idx = self._index([emp])
        # detected 120 min, approved 1.5h = 90 min → min = 90.
        self.assertEqual(payable_overtime_minutes(emp, _DATE, 120, idx), 90)

    def test_management_review_zero_until_approved(self):
        emp = _employee(self.company, 'management_review')
        OvertimeRequest.objects.create(
            company=self.company, employee=emp, date=_DATE,
            requested_hours=Decimal('2.00'), status='pending', source='detected',
        )
        idx = self._index([emp])
        self.assertEqual(payable_overtime_minutes(emp, _DATE, 120, idx), 0)

    def test_not_allowed_pays_only_with_override(self):
        emp = _employee(self.company, 'not_allowed')
        idx = self._index([emp])
        self.assertEqual(payable_overtime_minutes(emp, _DATE, 120, idx), 0)
        OvertimeRequest.objects.create(
            company=self.company, employee=emp, date=_DATE,
            requested_hours=Decimal('2.00'), status='approved', source='hr',
        )
        idx = self._index([emp])
        self.assertEqual(payable_overtime_minutes(emp, _DATE, 120, idx), 120)

    def test_approved_hours_falls_back_to_requested(self):
        emp = _employee(self.company, 'request_required')
        OvertimeRequest.objects.create(
            company=self.company, employee=emp, date=_DATE,
            requested_hours=Decimal('1.00'), approved_hours=None,
            status='approved', source='employee',
        )
        idx = self._index([emp])
        # approved_hours None → fall back to requested 1.0h = 60 min.
        self.assertEqual(payable_overtime_minutes(emp, _DATE, 120, idx), 60)


class AutoCreateSignalTests(TestCase):
    def setUp(self):
        self.company = _company()

    def _attendance_record(self, emp, overtime_minutes):
        from attendance.models import AttendanceRecord
        return AttendanceRecord.objects.create(
            company=self.company, employee=emp, date=_DATE,
            time_in=datetime.time(14, 0), time_out=datetime.time(23, 0),
            overtime_minutes=overtime_minutes, status='present',
        )

    def test_management_review_detected_ot_creates_pending(self):
        emp = _employee(self.company, 'management_review')
        self._attendance_record(emp, 120)
        req = OvertimeRequest.objects.get(employee=emp, date=_DATE)
        self.assertEqual(req.status, 'pending')
        self.assertEqual(req.source, 'detected')
        self.assertEqual(req.requested_hours, Decimal('2.00'))

    def test_no_request_when_zero_overtime(self):
        emp = _employee(self.company, 'management_review')
        self._attendance_record(emp, 0)
        self.assertFalse(OvertimeRequest.objects.filter(employee=emp, date=_DATE).exists())

    def test_no_request_for_non_management_review_policy(self):
        for policy in ['not_allowed', 'automatic', 'request_required']:
            emp = _employee(self.company, policy)
            self._attendance_record(emp, 120)
            self.assertFalse(
                OvertimeRequest.objects.filter(employee=emp, date=_DATE).exists(),
                f'unexpected request created for policy={policy}',
            )

    def test_idempotent_updates_pending_requested_hours(self):
        emp = _employee(self.company, 'management_review')
        rec = self._attendance_record(emp, 120)
        rec.overtime_minutes = 180
        rec.save(update_fields=['overtime_minutes'])
        reqs = OvertimeRequest.objects.filter(employee=emp, date=_DATE)
        self.assertEqual(reqs.count(), 1)
        self.assertEqual(reqs.first().requested_hours, Decimal('3.00'))

    def test_does_not_override_reviewed_request(self):
        emp = _employee(self.company, 'management_review')
        rec = self._attendance_record(emp, 120)
        req = OvertimeRequest.objects.get(employee=emp, date=_DATE)
        req.status = 'approved'
        req.approved_hours = Decimal('2.00')
        req.save(update_fields=['status', 'approved_hours'])
        rec.overtime_minutes = 240
        rec.save(update_fields=['overtime_minutes'])
        req.refresh_from_db()
        self.assertEqual(req.status, 'approved')
        self.assertEqual(req.requested_hours, Decimal('2.00'))  # unchanged


class PortalOvertimeViewTests(TestCase):
    def setUp(self):
        self.company = _company()
        self.user = User.objects.create_user('emp1', password='pw')
        self.emp = _employee(self.company, 'request_required')
        self.emp.user = self.user
        self.emp.save(update_fields=['user'])
        self.client.force_login(self.user)

    def test_list_page_loads(self):
        resp = self.client.get(reverse('portal:overtime_list'))
        self.assertEqual(resp.status_code, 200)

    # Write requests pass through the license middleware; patch it active
    # (same pattern as attendance portal tests).
    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_employee_can_submit_request(self, _mock_license):
        resp = self.client.post(reverse('portal:overtime_new'), {
            'date': _DATE.isoformat(),
            'requested_hours': '2.00',
            'reason': 'Project deadline',
        })
        self.assertEqual(resp.status_code, 302)
        req = OvertimeRequest.objects.get(employee=self.emp, date=_DATE)
        self.assertEqual(req.status, 'pending')
        self.assertEqual(req.source, 'employee')
        self.assertEqual(req.company, self.company)

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_duplicate_date_is_rejected_gracefully(self, _mock_license):
        OvertimeRequest.objects.create(
            company=self.company, employee=self.emp, date=_DATE,
            requested_hours=Decimal('1.00'), status='pending', source='employee',
        )
        resp = self.client.post(reverse('portal:overtime_new'), {
            'date': _DATE.isoformat(),
            'requested_hours': '2.00',
            'reason': 'second attempt',
        })
        self.assertEqual(OvertimeRequest.objects.filter(employee=self.emp, date=_DATE).count(), 1)
        self.assertIn(resp.status_code, (200, 302))
