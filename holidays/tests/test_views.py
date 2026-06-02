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
