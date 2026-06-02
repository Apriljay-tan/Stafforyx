"""Tests for employee-only portal confinement (EmployeePortalOnlyMiddleware)."""

from django.contrib.auth.models import User
from django.test import TestCase

from accounts.access import is_employee_only_user
from accounts.models import UserProfile


class IsEmployeeOnlyUserHelperTests(TestCase):
    def test_employee_role_profile_is_employee_only(self):
        user = User.objects.create_user('emp', password='pass')
        UserProfile.objects.create(user=user, role='employee')
        self.assertTrue(is_employee_only_user(user))

    def test_superuser_is_not_employee_only(self):
        admin = User.objects.create_superuser('admin', password='pass')
        self.assertFalse(is_employee_only_user(admin))

    def test_hr_admin_is_not_employee_only(self):
        user = User.objects.create_user('hr', password='pass')
        UserProfile.objects.create(user=user, role='hr_admin')
        self.assertFalse(is_employee_only_user(user))

    def test_user_without_profile_is_not_employee_only(self):
        user = User.objects.create_user('noprofile', password='pass')
        self.assertFalse(is_employee_only_user(user))

    def test_anonymous_is_not_employee_only(self):
        from django.contrib.auth.models import AnonymousUser
        self.assertFalse(is_employee_only_user(AnonymousUser()))


class EmployeePortalOnlyMiddlewareTests(TestCase):
    def setUp(self):
        self.employee = User.objects.create_user('emp', password='pass')
        UserProfile.objects.create(user=self.employee, role='employee')
        self.admin = User.objects.create_superuser('admin', password='pass')

    # ── employee-only is redirected away from management pages ──────────────

    def _assert_redirects_to_portal(self, path):
        resp = self.client.get(path)
        self.assertRedirects(resp, '/portal/', fetch_redirect_response=False)

    def test_employee_only_dashboard_redirects_to_portal(self):
        self.client.login(username='emp', password='pass')
        self._assert_redirects_to_portal('/')

    def test_employee_only_employees_redirects_to_portal(self):
        self.client.login(username='emp', password='pass')
        self._assert_redirects_to_portal('/employees/')

    def test_employee_only_payroll_redirects_to_portal(self):
        self.client.login(username='emp', password='pass')
        self._assert_redirects_to_portal('/payroll/')

    def test_employee_only_reports_redirects_to_portal(self):
        self.client.login(username='emp', password='pass')
        self._assert_redirects_to_portal('/reports/')

    def test_employee_only_admin_redirects_to_portal(self):
        self.client.login(username='emp', password='pass')
        self._assert_redirects_to_portal('/admin/')

    def test_employee_only_license_status_redirects_to_portal(self):
        self.client.login(username='emp', password='pass')
        self._assert_redirects_to_portal('/licenses/status/')

    def test_employee_only_never_sees_access_restricted(self):
        self.client.login(username='emp', password='pass')
        for path in ('/employees/', '/payroll/', '/reports/', '/admin/'):
            resp = self.client.get(path)
            self.assertNotEqual(resp.status_code, 403, f'{path} returned 403')
            self.assertEqual(resp.status_code, 302, f'{path} was not redirected')

    # ── employee-only keeps access to the portal and time clock ─────────────

    def test_employee_only_can_open_portal(self):
        self.client.login(username='emp', password='pass')
        self.assertEqual(self.client.get('/portal/').status_code, 200)

    def test_employee_only_can_open_attendance_time_clock(self):
        self.client.login(username='emp', password='pass')
        self.assertEqual(self.client.get('/attendance/portal/').status_code, 200)

    def test_employee_only_can_logout(self):
        self.client.login(username='emp', password='pass')
        resp = self.client.get('/accounts/logout/')
        self.assertNotEqual(resp.status_code, 200)  # redirected to login, not portal-trapped
        self.assertNotIn('/portal/', resp.get('Location', ''))

    # ── admins/superusers are unaffected ────────────────────────────────────

    def test_superuser_sees_dashboard(self):
        self.client.login(username='admin', password='pass')
        self.assertEqual(self.client.get('/').status_code, 200)
