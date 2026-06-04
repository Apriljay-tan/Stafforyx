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


def _employee(company, policy='no_ot', user=None):
    global _counter
    _counter += 1
    return Employee.objects.create(
        company=company,
        user=user,
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

    def test_no_ot_pays_zero_even_with_approved_request(self):
        emp = _employee(self.company, 'no_ot')
        idx = self._index([emp])
        self.assertEqual(payable_overtime_minutes(emp, _DATE, 120, idx), 0)
        OvertimeRequest.objects.create(
            company=self.company, employee=emp, date=_DATE,
            requested_hours=Decimal('2.00'), status='approved', source='hr',
        )
        idx = self._index([emp])
        self.assertEqual(payable_overtime_minutes(emp, _DATE, 120, idx), 0)

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


    def test_request_required_sums_multiple_approved_requests_but_caps_actual(self):
        emp = _employee(self.company, 'request_required')
        OvertimeRequest.objects.create(
            company=self.company, employee=emp, date=_DATE,
            requested_hours=Decimal('1.00'), approved_hours=Decimal('1.00'),
            status='approved', source='employee',
        )
        OvertimeRequest.objects.create(
            company=self.company, employee=emp, date=_DATE,
            requested_hours=Decimal('2.00'), approved_hours=Decimal('2.00'),
            status='approved', source='hr',
        )
        idx = self._index([emp])
        self.assertEqual(payable_overtime_minutes(emp, _DATE, 120, idx), 120)


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

    def test_no_request_auto_created_for_employee_ot_modes(self):
        for policy in ['no_ot', 'automatic', 'request_required']:
            emp = _employee(self.company, policy)
            self._attendance_record(emp, 120)
            self.assertFalse(
                OvertimeRequest.objects.filter(employee=emp, date=_DATE).exists(),
                f'unexpected request created for policy={policy}',
            )


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

    def test_request_required_employee_sees_request_button(self):
        resp = self.client.get(reverse('portal:overtime_list'))
        self.assertContains(resp, 'Request Overtime')

    def test_no_ot_employee_does_not_see_request_button_or_form(self):
        self.emp.overtime_policy = 'no_ot'
        self.emp.save(update_fields=['overtime_policy'])

        resp = self.client.get(reverse('portal:overtime_list'))
        self.assertNotContains(resp, 'Request Overtime')

        direct = self.client.get(reverse('portal:overtime_new'), follow=True)
        self.assertContains(direct, 'Overtime requests are not enabled for your account.')
        self.assertNotContains(direct, 'Submit Request')

    def test_automatic_employee_does_not_see_request_button_or_form(self):
        self.emp.overtime_policy = 'automatic'
        self.emp.save(update_fields=['overtime_policy'])

        resp = self.client.get(reverse('portal:overtime_list'))
        self.assertNotContains(resp, 'Request Overtime')
        self.assertContains(resp, 'Overtime is automatically computed from your attendance.')

        direct = self.client.get(reverse('portal:overtime_new'), follow=True)
        self.assertContains(direct, 'Overtime requests are not enabled for your account.')
        self.assertNotContains(direct, 'Submit Request')

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

    def test_employee_only_sees_own_overtime_requests(self):
        other_user = User.objects.create_user('emp2', password='pw')
        other_emp = _employee(self.company, 'request_required', user=other_user)
        OvertimeRequest.objects.create(
            company=self.company, employee=self.emp, date=_DATE,
            requested_hours=Decimal('1.00'), status='pending', source='employee',
            reason='Mine',
        )
        OvertimeRequest.objects.create(
            company=self.company, employee=other_emp, date=_DATE,
            requested_hours=Decimal('2.00'), status='approved', source='employee',
            reason='Other employee request',
        )

        resp = self.client.get(reverse('portal:overtime_list'))
        self.assertContains(resp, 'Mine')
        self.assertNotContains(resp, 'Other employee request')

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


class ManageOvertimeAccessTests(TestCase):
    def setUp(self):
        self.company = _company()
        self.other = Company.objects.create(name='Other Co')
        self.emp = _employee(self.company, 'request_required')
        self.req = OvertimeRequest.objects.create(
            company=self.company, employee=self.emp, date=_DATE,
            requested_hours=Decimal('2.00'), status='pending', source='employee',
        )

    def test_plain_employee_cannot_access_hr_pages(self):
        user = User.objects.create_user('plain', password='pw')
        self.client.force_login(user)
        resp = self.client.get(reverse('overtime:manage_overtime'))
        self.assertEqual(resp.status_code, 403)

    def test_hr_sees_only_in_scope_companies(self):
        from accounts.models import UserCompanyAccess, UserProfile
        hr = User.objects.create_user('hr', password='pw')
        profile, _ = UserProfile.objects.get_or_create(user=hr)
        # role != 'employee' so EmployeePortalOnlyMiddleware lets them into HR pages.
        profile.role = 'hr_admin'
        profile.can_manage_employees = True
        profile.save()
        UserCompanyAccess.objects.create(user=hr, company=self.company, is_active=True)
        self.client.force_login(hr)

        # In-scope request visible.
        resp = self.client.get(reverse('overtime:manage_overtime'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.emp.last_name)

        # Out-of-scope request not visible.
        other_emp = Employee.objects.create(
            company=self.other, employee_id='X1', first_name='Out', last_name='Scope',
            date_hired=datetime.date(2024, 1, 1), status='active',
        )
        OvertimeRequest.objects.create(
            company=self.other, employee=other_emp, date=_DATE,
            requested_hours=Decimal('1.00'), status='pending', source='employee',
        )
        resp = self.client.get(reverse('overtime:manage_overtime'))
        self.assertNotContains(resp, 'Scope')

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_superuser_can_approve_and_sets_review_fields(self, _mock_license):
        su = User.objects.create_superuser('root', 'root@x.com', 'pw')
        self.client.force_login(su)
        resp = self.client.post(
            reverse('overtime:manage_overtime_detail', args=[self.req.pk]),
            {'action': 'approve', 'approved_hours': '1.50', 'manager_note': 'ok'},
        )
        self.assertEqual(resp.status_code, 302)
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, 'approved')
        self.assertEqual(self.req.approved_hours, Decimal('1.50'))
        self.assertEqual(self.req.reviewed_by, su)
        self.assertIsNotNone(self.req.reviewed_at)

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_approve_defaults_approved_hours_to_requested(self, _mock_license):
        su = User.objects.create_superuser('root2', 'root2@x.com', 'pw')
        self.client.force_login(su)
        self.client.post(
            reverse('overtime:manage_overtime_detail', args=[self.req.pk]),
            {'action': 'approve', 'approved_hours': '', 'manager_note': ''},
        )
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, 'approved')
        self.assertEqual(self.req.approved_hours, Decimal('2.00'))
