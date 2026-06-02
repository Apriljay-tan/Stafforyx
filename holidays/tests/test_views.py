import datetime
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from accounts.models import UserCompanyAccess, UserProfile
from companies.models import Company
from holidays.models import Holiday

D = datetime.date


class HolidayViewTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="V", email="v@t.com")
        self.admin = User.objects.create_superuser("admin", password="pass")
        self.client.login(username="admin", password="pass")
        session = self.client.session
        session["selected_company_id"] = self.company.pk
        session.save()

    def test_list_requires_login(self):
        self.client.logout()
        resp = self.client.get(reverse("holidays:holiday_list"))
        self.assertIn(resp.status_code, [302, 403])

    def test_list_shows_company_holidays(self):
        resp = self.client.get(reverse("holidays:holiday_list"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Labor Day")  # auto-seeded

    # POST views are guarded by LicenseReadOnlyMiddleware, which redirects
    # authenticated POSTs when no active license exists. Patch it active so we
    # exercise the holiday views themselves (same pattern as the payroll tests).
    @patch("licenses.middleware.is_license_active", return_value=True)
    def test_toggle_enable_disable(self, _mock):
        h = Holiday.objects.filter(company=self.company).first()
        self.assertTrue(h.is_enabled)
        resp = self.client.post(reverse("holidays:holiday_toggle", args=[h.pk]))
        self.assertEqual(resp.status_code, 302)
        h.refresh_from_db()
        self.assertFalse(h.is_enabled)

    @patch("licenses.middleware.is_license_active", return_value=True)
    def test_add_custom_holiday(self, _mock):
        resp = self.client.post(reverse("holidays:holiday_add"), {
            "name": "Foundation Day", "date": "2026-07-15",
            "holiday_type": "company", "is_paid": "on",
            "no_work_pay_pct": "100", "worked_multiplier": "1.00",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Holiday.objects.filter(
            company=self.company, name="Foundation Day").exists())

    @patch("licenses.middleware.is_license_active", return_value=True)
    def test_company_scoping_blocks_other_company_holiday(self, _mock):
        # Superusers bypass company scoping by design, so use a scoped HR user
        # who can manage payroll for self.company but has no access to `other`.
        other = Company.objects.create(name="Other", email="o@t.com")
        hr = User.objects.create_user("hr", password="pass")
        UserProfile.objects.create(
            user=hr, role="hr_admin", is_active_stafforyx=True, can_manage_payroll=True)
        UserCompanyAccess.objects.create(
            user=hr, company=self.company, role="hr_admin", is_active=True)
        self.client.logout()
        self.client.login(username="hr", password="pass")
        h = Holiday.objects.filter(company=other).first()
        resp = self.client.post(reverse("holidays:holiday_toggle", args=[h.pk]))
        self.assertIn(resp.status_code, [403, 404])


class HolidayCompanySelectionTests(TestCase):
    """UX: opening /holidays/ with no selected company shows an in-app selector
    instead of redirecting to the dashboard."""

    def _scoped_user(self, username, *companies):
        user = User.objects.create_user(username, password="pass")
        UserProfile.objects.create(
            user=user, role="hr_admin", is_active_stafforyx=True, can_manage_payroll=True)
        for c in companies:
            UserCompanyAccess.objects.create(
                user=user, company=c, role="hr_admin", is_active=True)
        return user

    def test_superuser_no_company_sees_selector(self):
        # Two companies + superuser, no session selection -> selector page.
        c1 = Company.objects.create(name="Alpha Co", email="a@t.com")
        c2 = Company.objects.create(name="Beta Co", email="b@t.com")
        User.objects.create_superuser("admin", password="pass")
        self.client.login(username="admin", password="pass")
        resp = self.client.get(reverse("holidays:holiday_list"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Select a company to manage holidays")
        self.assertContains(resp, "Alpha Co")
        self.assertContains(resp, "Beta Co")
        # Did not bounce to the dashboard.
        self.assertNotEqual(resp.get("Location", ""), "/")

    def test_after_selecting_company_shows_holiday_list(self):
        c1 = Company.objects.create(name="Alpha Co", email="a@t.com")
        Company.objects.create(name="Beta Co", email="b@t.com")
        User.objects.create_superuser("admin", password="pass")
        self.client.login(username="admin", password="pass")
        # Persist the choice via the shared Stafforyx company selector endpoint.
        self.client.post(reverse("accounts:select_company"), {
            "company_id": str(c1.pk),
            "next": reverse("holidays:holiday_list"),
        })
        resp = self.client.get(reverse("holidays:holiday_list"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Alpha Co")
        self.assertContains(resp, "Labor Day")  # auto-seeded holiday list rendered

    def test_selected_company_page_shows_visible_switcher(self):
        c1 = Company.objects.create(name="Alpha Co", email="a@t.com")
        c2 = Company.objects.create(name="Beta Co", email="b@t.com")
        User.objects.create_superuser("admin", password="pass")
        self.client.login(username="admin", password="pass")
        session = self.client.session
        session["selected_company_id"] = c1.pk
        session.save()

        resp = self.client.get(reverse("holidays:holiday_list"))

        self.assertContains(resp, "Holidays \u2014 Alpha Co")
        self.assertContains(resp, "Current company:")
        self.assertContains(resp, "Switch Company")
        self.assertContains(resp, f'<option value="{c1.pk}" selected>Alpha Co</option>', html=True)
        self.assertContains(resp, f'<option value="{c2.pk}">Beta Co</option>', html=True)

    def test_switcher_post_updates_session_and_redirects_back_to_holidays(self):
        c1 = Company.objects.create(name="Alpha Co", email="a@t.com")
        c2 = Company.objects.create(name="Beta Co", email="b@t.com")
        User.objects.create_superuser("admin", password="pass")
        self.client.login(username="admin", password="pass")
        session = self.client.session
        session["selected_company_id"] = c1.pk
        session.save()

        resp = self.client.post(reverse("accounts:select_company"), {
            "company_id": str(c2.pk),
            "next": reverse("holidays:holiday_list"),
        })

        self.assertRedirects(resp, reverse("holidays:holiday_list"), fetch_redirect_response=False)
        self.assertEqual(self.client.session["selected_company_id"], c2.pk)

    def test_normal_user_switcher_only_lists_accessible_companies(self):
        c1 = Company.objects.create(name="Alpha Co", email="a@t.com")
        c2 = Company.objects.create(name="Beta Co", email="b@t.com")
        hidden = Company.objects.create(name="Hidden Co", email="hidden@t.com")
        user = self._scoped_user("hr", c1, c2)
        self.client.login(username=user.username, password="pass")
        session = self.client.session
        session["selected_company_id"] = c1.pk
        session.save()

        resp = self.client.get(reverse("holidays:holiday_list"))

        self.assertContains(resp, "Alpha Co")
        self.assertContains(resp, "Beta Co")
        self.assertNotContains(resp, hidden.name)

    def test_employee_only_user_cannot_access_holidays(self):
        employee = User.objects.create_user("employee", password="pass")
        UserProfile.objects.create(
            user=employee, role="employee", is_active_stafforyx=True, can_manage_payroll=False)
        self.client.login(username=employee.username, password="pass")

        resp = self.client.get(reverse("holidays:holiday_list"))

        self.assertRedirects(resp, reverse("portal:dashboard"), fetch_redirect_response=False)

    def test_single_accessible_company_auto_selects(self):
        # Exactly one company in the system + superuser -> auto-select, no selector.
        only = Company.objects.create(name="Solo Co", email="s@t.com")
        User.objects.create_superuser("admin", password="pass")
        self.client.login(username="admin", password="pass")
        resp = self.client.get(reverse("holidays:holiday_list"), follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "Select a company to manage holidays")
        self.assertContains(resp, "Solo Co")
        self.assertContains(resp, "Labor Day")
        self.assertEqual(self.client.session.get("selected_company_id"), only.pk)

    def test_company_scoped_holidays_remain_isolated(self):
        c1 = Company.objects.create(name="Alpha Co", email="a@t.com")
        c2 = Company.objects.create(name="Beta Co", email="b@t.com")
        # Custom holidays unique to each company.
        Holiday.objects.create(
            company=c1, name="Alpha Founders Day", date=D(2026, 7, 1),
            holiday_type="company", source="company")
        Holiday.objects.create(
            company=c2, name="Beta Founders Day", date=D(2026, 7, 2),
            holiday_type="company", source="company")
        User.objects.create_superuser("admin", password="pass")
        self.client.login(username="admin", password="pass")
        session = self.client.session
        session["selected_company_id"] = c1.pk
        session.save()
        resp = self.client.get(reverse("holidays:holiday_list"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Alpha Founders Day")
        self.assertNotContains(resp, "Beta Founders Day")  # other company's holiday hidden
