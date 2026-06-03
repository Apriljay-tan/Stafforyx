import datetime

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from companies.models import Company
from employees.models import Employee

from .models import UserCompanyAccess, UserProfile
from .company_access import (
    get_accessible_companies,
    user_can_access_company,
    filter_queryset_by_user_companies,
)


def _make_company(name='Company A'):
    return Company.objects.create(name=name)


def _make_user(username, password='testpass123', is_superuser=False):
    if is_superuser:
        return User.objects.create_superuser(username=username, password=password)
    return User.objects.create_user(username=username, password=password)


def _grant_access(user, company, role='viewer'):
    return UserCompanyAccess.objects.create(user=user, company=company, role=role, is_active=True)


_emp_counter = 0


def _make_employee(company):
    global _emp_counter
    _emp_counter += 1
    return Employee.objects.create(
        company=company,
        employee_id=f'TST{_emp_counter:03d}',
        first_name='Test',
        last_name='Emp',
        date_hired=datetime.date(2024, 1, 1),
        status='active',
    )


class GetAccessibleCompaniesTests(TestCase):
    def setUp(self):
        self.company_a = _make_company('Company A')
        self.company_b = _make_company('Company B')
        self.superuser = _make_user('su', is_superuser=True)
        self.user_a = _make_user('user_a')
        _grant_access(self.user_a, self.company_a)

    def test_superuser_sees_all_companies(self):
        qs = get_accessible_companies(self.superuser)
        self.assertIn(self.company_a, qs)
        self.assertIn(self.company_b, qs)

    def test_normal_user_sees_only_assigned_company(self):
        qs = get_accessible_companies(self.user_a)
        self.assertIn(self.company_a, qs)
        self.assertNotIn(self.company_b, qs)

    def test_user_with_no_access_sees_nothing(self):
        user_none = _make_user('user_none')
        qs = get_accessible_companies(user_none)
        self.assertEqual(qs.count(), 0)

    def test_inactive_access_is_excluded(self):
        user_inactive = _make_user('user_inactive')
        UserCompanyAccess.objects.create(
            user=user_inactive, company=self.company_a, role='viewer', is_active=False
        )
        qs = get_accessible_companies(user_inactive)
        self.assertEqual(qs.count(), 0)


class FilterCompanyQuerysetTests(TestCase):
    """
    filter_queryset_by_user_companies must accept a Company queryset itself
    (used to build company pickers) without raising a FieldError.
    Regression: scoped admins previously got a 500 on /payroll/.
    """

    def setUp(self):
        self.company_a = _make_company('Company A')
        self.company_b = _make_company('Company B')
        self.superuser = _make_user('su_filter', is_superuser=True)
        self.scoped = _make_user('scoped_admin')
        UserProfile.objects.create(
            user=self.scoped, role='hr_admin', is_active_stafforyx=True,
            can_manage_payroll=True, company=self.company_a,
        )
        _grant_access(self.scoped, self.company_a, role='hr_admin')

    def test_company_queryset_scoped_to_accessible(self):
        from companies.models import Company
        qs = filter_queryset_by_user_companies(Company.objects.all(), self.scoped)
        self.assertIn(self.company_a, qs)
        self.assertNotIn(self.company_b, qs)

    def test_company_queryset_superuser_sees_all(self):
        from companies.models import Company
        qs = filter_queryset_by_user_companies(Company.objects.all(), self.superuser)
        self.assertEqual(qs.count(), 2)

    def test_scoped_admin_can_open_payroll_list(self):
        from django.urls import reverse
        self.client.force_login(self.scoped)
        response = self.client.get(reverse('payroll:payroll_record_list'))
        self.assertEqual(response.status_code, 200)


class UserCanAccessCompanyTests(TestCase):
    def setUp(self):
        self.company_a = _make_company('Company A')
        self.company_b = _make_company('Company B')
        self.superuser = _make_user('su', is_superuser=True)
        self.user_a = _make_user('user_a')
        _grant_access(self.user_a, self.company_a)

    def test_superuser_can_access_any_company(self):
        self.assertTrue(user_can_access_company(self.superuser, self.company_a))
        self.assertTrue(user_can_access_company(self.superuser, self.company_b))

    def test_user_can_access_assigned_company(self):
        self.assertTrue(user_can_access_company(self.user_a, self.company_a))

    def test_user_cannot_access_unassigned_company(self):
        self.assertFalse(user_can_access_company(self.user_a, self.company_b))


class FilterQuerysetByUserCompaniesTests(TestCase):
    def setUp(self):
        self.company_a = _make_company('Company A')
        self.company_b = _make_company('Company B')
        self.superuser = _make_user('su', is_superuser=True)
        self.user_a = _make_user('user_a')
        _grant_access(self.user_a, self.company_a)
        self.emp_a = _make_employee(self.company_a)
        self.emp_b = _make_employee(self.company_b)

    def test_superuser_sees_all_employees(self):
        qs = filter_queryset_by_user_companies(Employee.objects.all(), self.superuser)
        pks = list(qs.values_list('pk', flat=True))
        self.assertIn(self.emp_a.pk, pks)
        self.assertIn(self.emp_b.pk, pks)

    def test_company_a_user_sees_only_company_a_employees(self):
        qs = filter_queryset_by_user_companies(Employee.objects.all(), self.user_a)
        pks = list(qs.values_list('pk', flat=True))
        self.assertIn(self.emp_a.pk, pks)
        self.assertNotIn(self.emp_b.pk, pks)


class CompanyAccessViewTests(TestCase):
    """HTTP-level isolation: company A user cannot access company B objects."""

    def setUp(self):
        self.company_a = _make_company('Company A')
        self.company_b = _make_company('Company B')

        self.user_a = _make_user('user_a')
        _grant_access(self.user_a, self.company_a, role='hr_admin')
        UserProfile.objects.create(
            user=self.user_a,
            role='hr_admin',
            is_active_stafforyx=True,
            can_manage_employees=True,
        )

        self.emp_b = _make_employee(self.company_b)

    def _login_a(self):
        self.client.login(username='user_a', password='testpass123')

    def test_employee_list_requires_login(self):
        response = self.client.get(reverse('employees:employee_list'))
        self.assertIn(response.status_code, [302, 403])

    def test_user_a_cannot_access_employee_b_detail(self):
        self._login_a()
        response = self.client.get(
            reverse('employees:employee_detail', kwargs={'pk': self.emp_b.pk})
        )
        self.assertEqual(response.status_code, 403)

    def test_user_a_cannot_edit_employee_b(self):
        self._login_a()
        response = self.client.get(
            reverse('employees:employee_edit', kwargs={'pk': self.emp_b.pk})
        )
        self.assertEqual(response.status_code, 403)

    def test_user_a_cannot_reach_delete_confirm_for_employee_b(self):
        # GET to the confirm-delete page also enforces company access.
        # (POST is blocked first by LicenseReadOnlyMiddleware in test env.)
        self._login_a()
        response = self.client.get(
            reverse('employees:employee_delete', kwargs={'pk': self.emp_b.pk})
        )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Employee.objects.filter(pk=self.emp_b.pk).exists())

    def test_superuser_can_access_any_employee(self):
        superuser = _make_user('su_test', is_superuser=True)
        self.client.login(username='su_test', password='testpass123')
        response = self.client.get(
            reverse('employees:employee_detail', kwargs={'pk': self.emp_b.pk})
        )
        self.assertEqual(response.status_code, 200)


class SelectCompanyViewTests(TestCase):
    def setUp(self):
        self.company_a = _make_company('Company A')
        self.company_b = _make_company('Company B')
        self.user_a = _make_user('user_a')
        _grant_access(self.user_a, self.company_a)

    def test_select_company_sets_session(self):
        self.client.login(username='user_a', password='testpass123')
        response = self.client.post(
            reverse('accounts:select_company'),
            {'company_id': self.company_a.pk, 'next': '/'},
        )
        self.assertEqual(self.client.session.get('selected_company_id'), self.company_a.pk)

    def test_select_inaccessible_company_raises_403(self):
        self.client.login(username='user_a', password='testpass123')
        response = self.client.post(
            reverse('accounts:select_company'),
            {'company_id': self.company_b.pk, 'next': '/'},
        )
        self.assertEqual(response.status_code, 403)
