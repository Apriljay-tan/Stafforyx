import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

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
