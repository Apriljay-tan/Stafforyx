import datetime
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from accounts.models import UserCompanyAccess, UserProfile
from companies.models import Company
from employees.models import Employee

from .models import CashAdvanceRequest

_RELEASE_DATE = datetime.date(2026, 6, 30)
_counter = 0


def _company(name='CA Co'):
    return Company.objects.create(name=name)


def _employee(company, user=None, emp_id=None):
    global _counter
    _counter += 1
    return Employee.objects.create(
        company=company,
        user=user,
        employee_id=emp_id or f'CA{_counter:03d}',
        first_name='Cash',
        last_name=f'Advance{_counter}',
        email=f'ca{_counter}@test.com',
        date_hired=datetime.date(2024, 1, 1),
        status='active',
    )


def _ca(company, employee, **kwargs):
    defaults = dict(
        company=company, employee=employee,
        amount=Decimal('1000.00'), reason='Need funds',
        status=CashAdvanceRequest.STATUS_PENDING,
    )
    defaults.update(kwargs)
    return CashAdvanceRequest.objects.create(**defaults)


def _hr_user(company, username='hr', *, can_manage_payroll=True,
             can_manage_employees=False, role='hr_admin'):
    user = User.objects.create_user(username, password='pw')
    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.role = role
    profile.can_manage_payroll = can_manage_payroll
    profile.can_manage_employees = can_manage_employees
    profile.is_active_stafforyx = True
    profile.save()
    UserCompanyAccess.objects.create(user=user, company=company, is_active=True)
    return user


# ── Employee portal: create / view / ownership ────────────────────────────────

class PortalCashAdvanceTests(TestCase):
    def setUp(self):
        self.company = _company()
        self.user = User.objects.create_user('emp1', password='pw')
        self.emp = _employee(self.company, user=self.user)
        self.client.force_login(self.user)

    def test_list_page_loads_with_request_button(self):
        resp = self.client.get(reverse('portal:ca_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Request Cash Advance')

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_employee_can_create_own_ca_request(self, _mock_license):
        resp = self.client.post(reverse('portal:ca_new'), {
            'amount': '1500.00',
            'reason': 'Medical bill',
            'requested_release_date': _RELEASE_DATE.isoformat(),
        })
        self.assertEqual(resp.status_code, 302)
        ca = CashAdvanceRequest.objects.get(employee=self.emp)
        self.assertEqual(ca.status, CashAdvanceRequest.STATUS_PENDING)
        self.assertEqual(ca.company, self.company)
        self.assertEqual(ca.amount, Decimal('1500.00'))
        self.assertEqual(ca.requested_release_date, _RELEASE_DATE)

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_release_date_is_optional(self, _mock_license):
        resp = self.client.post(reverse('portal:ca_new'), {
            'amount': '500.00',
            'reason': 'Groceries',
        })
        self.assertEqual(resp.status_code, 302)
        ca = CashAdvanceRequest.objects.get(employee=self.emp)
        self.assertIsNone(ca.requested_release_date)

    def test_employee_can_view_own_ca_requests(self):
        _ca(self.company, self.emp, reason='My very own CA')
        resp = self.client.get(reverse('portal:ca_list'))
        self.assertContains(resp, 'My very own CA')

    def test_employee_cannot_view_other_employee_ca_requests(self):
        other = _employee(self.company)
        _ca(self.company, other, reason='Someone elses CA')
        resp = self.client.get(reverse('portal:ca_list'))
        self.assertNotContains(resp, 'Someone elses CA')

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_employee_cannot_edit_released_request(self, _mock_license):
        ca = _ca(
            self.company, self.emp, amount=Decimal('1000.00'),
            status=CashAdvanceRequest.STATUS_RELEASED,
        )
        # GET edit page should bounce back to the list.
        resp = self.client.get(reverse('portal:ca_edit', args=[ca.pk]), follow=True)
        self.assertContains(resp, 'can no longer be edited')
        # POST edit must not change the amount.
        self.client.post(reverse('portal:ca_edit', args=[ca.pk]), {
            'amount': '9999.00', 'reason': 'hax',
        })
        ca.refresh_from_db()
        self.assertEqual(ca.amount, Decimal('1000.00'))
        self.assertEqual(ca.status, CashAdvanceRequest.STATUS_RELEASED)

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_employee_can_edit_pending_request(self, _mock_license):
        ca = _ca(self.company, self.emp, amount=Decimal('1000.00'))
        self.client.post(reverse('portal:ca_edit', args=[ca.pk]), {
            'amount': '1200.00', 'reason': 'updated reason',
        })
        ca.refresh_from_db()
        self.assertEqual(ca.amount, Decimal('1200.00'))

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_employee_cannot_edit_another_employees_request(self, _mock_license):
        other = _employee(self.company)
        ca = _ca(self.company, other, amount=Decimal('1000.00'))
        resp = self.client.post(reverse('portal:ca_edit', args=[ca.pk]), {
            'amount': '5000.00', 'reason': 'theft',
        })
        self.assertEqual(resp.status_code, 404)
        ca.refresh_from_db()
        self.assertEqual(ca.amount, Decimal('1000.00'))

    def test_unlinked_user_sees_friendly_message(self):
        lone = User.objects.create_user('lone', password='pw')
        self.client.force_login(lone)
        resp = self.client.get(reverse('portal:ca_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'portal/no_employee.html')


# ── HR/Admin management: scoping, approve, reject, release, permissions ────────

class ManageCashAdvanceTests(TestCase):
    def setUp(self):
        self.company = _company('Scope Co')
        self.other = _company('Other Co')
        self.emp = _employee(self.company)
        self.ca = _ca(self.company, self.emp, reason='In scope CA')

    def test_hr_sees_only_company_scoped_requests(self):
        other_emp = _employee(self.other)
        _ca(self.other, other_emp, reason='Out of scope CA')

        hr = _hr_user(self.company)
        self.client.force_login(hr)
        resp = self.client.get(reverse('cash_advance:manage_ca') + '?tab=history')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.emp.last_name)
        self.assertNotContains(resp, other_emp.last_name)

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_hr_can_approve_request(self, _mock_license):
        hr = _hr_user(self.company)
        self.client.force_login(hr)
        resp = self.client.post(
            reverse('cash_advance:manage_ca_detail', args=[self.ca.pk]),
            {'action': 'approve', 'manager_note': 'ok'},
        )
        self.assertEqual(resp.status_code, 302)
        self.ca.refresh_from_db()
        self.assertEqual(self.ca.status, CashAdvanceRequest.STATUS_APPROVED)
        self.assertEqual(self.ca.approved_by, hr)
        self.assertIsNotNone(self.ca.approved_at)

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_hr_can_reject_request(self, _mock_license):
        hr = _hr_user(self.company)
        self.client.force_login(hr)
        self.client.post(
            reverse('cash_advance:manage_ca_detail', args=[self.ca.pk]),
            {'action': 'reject'},
        )
        self.ca.refresh_from_db()
        self.assertEqual(self.ca.status, CashAdvanceRequest.STATUS_REJECTED)
        self.assertEqual(self.ca.rejected_by, hr)
        self.assertIsNotNone(self.ca.rejected_at)

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_hr_can_cancel_request(self, _mock_license):
        hr = _hr_user(self.company)
        self.client.force_login(hr)
        self.client.post(
            reverse('cash_advance:manage_ca_detail', args=[self.ca.pk]),
            {'action': 'cancel', 'cancel_reason': 'duplicate'},
        )
        self.ca.refresh_from_db()
        self.assertEqual(self.ca.status, CashAdvanceRequest.STATUS_CANCELLED)

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_authorized_user_can_mark_released(self, _mock_license):
        self.ca.status = CashAdvanceRequest.STATUS_APPROVED
        self.ca.save(update_fields=['status'])
        payroll = _hr_user(self.company, username='payroll', can_manage_payroll=True)
        self.client.force_login(payroll)
        self.client.post(
            reverse('cash_advance:manage_ca_detail', args=[self.ca.pk]),
            {'action': 'release', 'release_note': 'cash handed over'},
        )
        self.ca.refresh_from_db()
        self.assertEqual(self.ca.status, CashAdvanceRequest.STATUS_RELEASED)
        self.assertEqual(self.ca.released_by, payroll)
        self.assertIsNotNone(self.ca.released_at)
        self.assertEqual(self.ca.release_note, 'cash handed over')

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_non_payroll_manager_cannot_release(self, _mock_license):
        self.ca.status = CashAdvanceRequest.STATUS_APPROVED
        self.ca.save(update_fields=['status'])
        # HR with employee-management only — may manage but not release money.
        hr = _hr_user(
            self.company, username='hronly',
            can_manage_payroll=False, can_manage_employees=True,
        )
        self.client.force_login(hr)
        resp = self.client.post(
            reverse('cash_advance:manage_ca_detail', args=[self.ca.pk]),
            {'action': 'release', 'release_note': 'should fail'},
        )
        self.assertEqual(resp.status_code, 403)
        self.ca.refresh_from_db()
        self.assertEqual(self.ca.status, CashAdvanceRequest.STATUS_APPROVED)

    def test_unauthorized_user_cannot_access_management(self):
        plain = User.objects.create_user('plain', password='pw')
        self.client.force_login(plain)
        resp = self.client.get(reverse('cash_advance:manage_ca'))
        self.assertEqual(resp.status_code, 403)

    def test_hr_cannot_open_out_of_scope_detail(self):
        other_emp = _employee(self.other)
        other_ca = _ca(self.other, other_emp)
        hr = _hr_user(self.company)
        self.client.force_login(hr)
        resp = self.client.get(
            reverse('cash_advance:manage_ca_detail', args=[other_ca.pk])
        )
        self.assertEqual(resp.status_code, 403)
