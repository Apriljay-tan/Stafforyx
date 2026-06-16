import datetime
from unittest.mock import patch

from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from accounts.models import UserCompanyAccess, UserProfile
from announcements.models import Announcement
from attendance.models import AttendanceRecord
from companies.models import Company
from documents.models import EmployeeDocument
from employees.models import Employee
from leaves.models import LeaveRequest, LeaveType
from notifications.models import Notification
from payroll.models import PayrollAdjustment, PayrollPeriod, PayrollRecord

from .models import IncidentReport


def _make_company(name):
    return Company.objects.create(name=name, email=f"{name.lower().replace(' ', '')}@test.com")


def _make_user(username, password="testpass123", is_superuser=False):
    if is_superuser:
        return User.objects.create_superuser(username=username, password=password)
    return User.objects.create_user(username=username, password=password)


def _make_employee(company, user, emp_id):
    return Employee.objects.create(
        company=company,
        user=user,
        employee_id=emp_id,
        first_name=emp_id,
        last_name="Employee",
        email=f"{emp_id.lower()}@test.com",
        date_hired=datetime.date(2024, 1, 1),
        status="active",
    )


class PortalAccessAndIsolationTests(TestCase):
    def setUp(self):
        self.company = _make_company("Portal Co")
        self.company_other = _make_company("Other Co")
        self.user_a = _make_user("portal_a")
        self.user_b = _make_user("portal_b")
        self.employee_a = _make_employee(self.company, self.user_a, "EMP-A")
        self.employee_b = _make_employee(self.company, self.user_b, "EMP-B")

        self.period = PayrollPeriod.objects.create(
            company=self.company,
            name="May 2026",
            start_date=datetime.date(2026, 5, 1),
            end_date=datetime.date(2026, 5, 15),
        )
        self.payslip_a = PayrollRecord.objects.create(
            company=self.company,
            payroll_period=self.period,
            employee=self.employee_a,
            net_pay=15000,
            gross_pay=18000,
            basic_pay=16000,
            daily_rate=1000,
            hourly_rate=125,
            status='approved',
        )
        self.payslip_b = PayrollRecord.objects.create(
            company=self.company,
            payroll_period=self.period,
            employee=self.employee_b,
            net_pay=14000,
            gross_pay=17000,
            basic_pay=15000,
            daily_rate=1000,
            hourly_rate=125,
            status='approved',
        )

        self.doc_a = EmployeeDocument.objects.create(
            company=self.company,
            employee=self.employee_a,
            title="A Contract",
            document_type="contract",
            file=SimpleUploadedFile("contract_a.txt", b"contract-a"),
        )
        self.doc_b = EmployeeDocument.objects.create(
            company=self.company,
            employee=self.employee_b,
            title="B Contract",
            document_type="contract",
            file=SimpleUploadedFile("contract_b.txt", b"contract-b"),
        )

        leave_type = LeaveType.objects.create(
            company=self.company,
            name="Vacation Leave",
            is_paid=True,
        )
        LeaveRequest.objects.create(
            company=self.company,
            employee=self.employee_a,
            leave_type=leave_type,
            start_date=datetime.date(2026, 5, 5),
            end_date=datetime.date(2026, 5, 5),
            total_days=1,
            reason="A leave",
            status="pending",
        )
        LeaveRequest.objects.create(
            company=self.company,
            employee=self.employee_b,
            leave_type=leave_type,
            start_date=datetime.date(2026, 5, 6),
            end_date=datetime.date(2026, 5, 6),
            total_days=1,
            reason="B leave",
            status="approved",
        )

        AttendanceRecord.objects.create(
            company=self.company,
            employee=self.employee_a,
            date=datetime.date(2026, 5, 2),
            time_in=datetime.time(8, 0),
            status="present",
        )
        AttendanceRecord.objects.create(
            company=self.company,
            employee=self.employee_b,
            date=datetime.date(2026, 5, 3),
            time_in=datetime.time(8, 0),
            status="present",
        )

        self.incident_a = IncidentReport.objects.create(
            company=self.company,
            employee=self.employee_a,
            incident_date=datetime.date(2026, 5, 4),
            title="A Incident",
            description="A description",
            location="A Site",
        )
        IncidentReport.objects.create(
            company=self.company,
            employee=self.employee_b,
            incident_date=datetime.date(2026, 5, 7),
            title="B Incident",
            description="B description",
            location="B Site",
        )
        self.announcement_a = Announcement.objects.create(
            company=self.company,
            title="Portal Announcement A",
            content="Visible to company A employees.",
            is_active=True,
        )
        self.announcement_b = Announcement.objects.create(
            company=self.company_other,
            title="Portal Announcement B",
            content="Should not be visible to company A employees.",
            is_active=True,
        )

    def _login_a(self):
        self.client.login(username="portal_a", password="testpass123")

    def test_portal_dashboard_requires_login(self):
        response = self.client.get(reverse("portal:dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)

    def test_portal_pages_render_for_linked_employee(self):
        self._login_a()
        for name in [
            "dashboard",
            "payslip_list",
            "documents",
            "leave_list",
            "incident_list",
            "attendance",
            "announcements",
        ]:
            with self.subTest(name=name):
                response = self.client.get(reverse(f"portal:{name}"))
                self.assertEqual(response.status_code, 200)

    def test_employee_only_sees_own_payslips_and_details(self):
        self._login_a()
        list_response = self.client.get(reverse("portal:payslip_list"))
        self.assertContains(list_response, self.payslip_a.payroll_period.name)
        self.assertNotContains(list_response, "B Incident")

        own_detail = self.client.get(reverse("portal:payslip_detail", args=[self.payslip_a.pk]))
        self.assertEqual(own_detail.status_code, 200)

        other_detail = self.client.get(reverse("portal:payslip_detail", args=[self.payslip_b.pk]))
        self.assertEqual(other_detail.status_code, 404)

    def test_portal_payslip_uses_calculated_adjustment_totals(self):
        PayrollAdjustment.objects.create(
            payroll_record=self.payslip_a,
            name="Cash Advance",
            adjustment_type="deduction",
            amount=500,
        )
        PayrollAdjustment.objects.create(
            payroll_record=self.payslip_a,
            name="Bonus",
            adjustment_type="earning",
            amount=1000,
        )
        PayrollRecord.objects.filter(pk=self.payslip_a.pk).update(
            gross_pay=18000,
            net_pay=18000,
        )

        self._login_a()
        detail = self.client.get(reverse("portal:payslip_detail", args=[self.payslip_a.pk]))
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.context["gross_pay"], 17000)
        self.assertEqual(detail.context["total_deductions"], 500)
        self.assertEqual(detail.context["net_pay"], 16500)

        listing = self.client.get(reverse("portal:payslip_list"))
        listed = next(ps for ps in listing.context["payslips"] if ps.pk == self.payslip_a.pk)
        self.assertEqual(listed.display_gross_pay, 17000)
        self.assertEqual(listed.display_net_pay, 16500)

    def test_employee_only_sees_own_documents_and_cannot_download_other(self):
        self._login_a()
        list_response = self.client.get(reverse("portal:documents"))
        self.assertContains(list_response, self.doc_a.title)
        self.assertNotContains(list_response, self.doc_b.title)

        own_download = self.client.get(reverse("portal:document_download", args=[self.doc_a.pk]))
        self.assertEqual(own_download.status_code, 200)

        other_download = self.client.get(reverse("portal:document_download", args=[self.doc_b.pk]))
        self.assertEqual(other_download.status_code, 404)

    def test_employee_only_sees_own_leaves_incidents_and_attendance(self):
        self._login_a()
        leaves_response = self.client.get(reverse("portal:leave_list"))
        self.assertContains(leaves_response, "A leave")
        self.assertNotContains(leaves_response, "B leave")

        incidents_response = self.client.get(reverse("portal:incident_list"))
        self.assertContains(incidents_response, self.incident_a.title)
        self.assertNotContains(incidents_response, "B Incident")

        attendance_response = self.client.get(reverse("portal:attendance"))
        self.assertContains(attendance_response, "May 02, 2026")
        self.assertNotContains(attendance_response, "May 03, 2026")

    def test_portal_no_employee_page_renders(self):
        orphan_user = _make_user("portal_orphan")
        self.client.login(username="portal_orphan", password="testpass123")
        response = self.client.get(reverse("portal:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "portal/no_employee.html")

    def test_time_clock_redirects_to_attendance_portal(self):
        self._login_a()
        response = self.client.get(reverse("portal:time_clock"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("attendance:attendance_portal"))

    def test_portal_dashboard_shows_company_announcements_only(self):
        self._login_a()
        response = self.client.get(reverse("portal:dashboard"))
        self.assertContains(response, self.announcement_a.title)
        self.assertNotContains(response, self.announcement_b.title)

    def test_portal_announcements_list_is_company_scoped(self):
        self._login_a()
        response = self.client.get(reverse("portal:announcements"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.announcement_a.title)
        self.assertNotContains(response, self.announcement_b.title)

    def test_portal_announcement_detail_blocks_other_company(self):
        self._login_a()
        own_detail = self.client.get(reverse("portal:announcement_detail", args=[self.announcement_a.pk]))
        self.assertEqual(own_detail.status_code, 200)
        other_detail = self.client.get(reverse("portal:announcement_detail", args=[self.announcement_b.pk]))
        self.assertEqual(other_detail.status_code, 404)

    def test_employee_cannot_create_edit_delete_announcements_from_portal(self):
        self._login_a()
        self.assertEqual(self.client.get("/portal/announcements/add/").status_code, 404)
        self.assertEqual(self.client.get(f"/portal/announcements/{self.announcement_a.pk}/edit/").status_code, 404)
        self.assertEqual(self.client.get(f"/portal/announcements/{self.announcement_a.pk}/delete/").status_code, 404)


class IncidentManagementScopeTests(TestCase):
    def setUp(self):
        self.company_a = _make_company("Company A")
        self.company_b = _make_company("Company B")
        self.hr_user = _make_user("hr_user")

        UserProfile.objects.create(
            user=self.hr_user,
            role="hr_admin",
            is_active_stafforyx=True,
            can_manage_employees=True,
        )
        UserCompanyAccess.objects.create(
            user=self.hr_user,
            company=self.company_a,
            role="hr_admin",
            is_active=True,
        )

        self.emp_a = _make_employee(self.company_a, _make_user("hr_emp_a"), "HR-A")
        self.emp_b = _make_employee(self.company_b, _make_user("hr_emp_b"), "HR-B")

        self.incident_a = IncidentReport.objects.create(
            company=self.company_a,
            employee=self.emp_a,
            incident_date=datetime.date(2026, 5, 1),
            title="Incident A",
            description="Scoped incident A",
            location="A",
        )
        self.incident_b = IncidentReport.objects.create(
            company=self.company_b,
            employee=self.emp_b,
            incident_date=datetime.date(2026, 5, 1),
            title="Incident B",
            description="Scoped incident B",
            location="B",
        )

    def test_hr_manage_incidents_is_company_scoped(self):
        self.client.login(username="hr_user", password="testpass123")
        response = self.client.get(reverse("portal:manage_incidents"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Incident A")
        self.assertNotContains(response, "Incident B")

    def test_hr_cannot_access_other_company_incident_detail(self):
        self.client.login(username="hr_user", password="testpass123")
        allowed = self.client.get(reverse("portal:manage_incident_detail", args=[self.incident_a.pk]))
        self.assertEqual(allowed.status_code, 200)

        forbidden = self.client.get(reverse("portal:manage_incident_detail", args=[self.incident_b.pk]))
        self.assertEqual(forbidden.status_code, 403)


class IncidentReportMainPanelTests(TestCase):
    def setUp(self):
        self.company = _make_company("Incident Co")
        self.other_company = _make_company("Other Incident Co")
        self.employee_user = _make_user("incident_employee")
        self.employee = _make_employee(self.company, self.employee_user, "INC-EMP")
        UserProfile.objects.create(
            user=self.employee_user,
            company=self.company,
            employee=self.employee,
            role="employee",
            is_active_stafforyx=True,
        )
        self.owner = self._authorized_user(
            "incident_owner",
            self.company,
            "owner",
            can_manage_employees=True,
        )
        self.company_admin = self._authorized_user(
            "incident_company_admin",
            self.company,
            "company_admin",
            can_manage_employees=True,
        )
        self.hr = self._authorized_user(
            "incident_hr",
            self.company,
            "hr_admin",
            can_manage_employees=True,
        )
        self.attendance = self._authorized_user(
            "incident_attendance",
            self.company,
            "attendance_officer",
            can_manage_attendance=True,
        )
        self.viewer = self._authorized_user("incident_viewer", self.company, "viewer")
        self.other_hr = self._authorized_user(
            "incident_other_hr",
            self.other_company,
            "hr_admin",
            can_manage_employees=True,
        )
        self.superuser = User.objects.create_superuser(
            "incident_root",
            "incident-root@example.com",
            "testpass123",
        )

    def _authorized_user(self, username, company, role, **profile_flags):
        user = _make_user(username)
        UserProfile.objects.create(
            user=user,
            role="hr_admin" if role != "viewer" else "manager",
            is_active_stafforyx=True,
            can_access_dashboard=True,
            **profile_flags,
        )
        UserCompanyAccess.objects.create(
            user=user,
            company=company,
            role=role,
            is_active=True,
        )
        return user

    def _incident_payload(self, title="Forklift near miss"):
        return {
            "incident_date": "2026-06-15",
            "incident_time": "09:30",
            "title": title,
            "description": "A forklift passed too close to the loading bay.",
            "location": "Warehouse A",
            "witnesses": "Shift lead",
        }

    def _create_incident(self, **overrides):
        data = {
            "company": self.company,
            "employee": self.employee,
            "incident_date": datetime.date(2026, 6, 15),
            "title": "Forklift near miss",
            "description": "A forklift passed too close to the loading bay.",
            "location": "Warehouse A",
        }
        data.update(overrides)
        return IncidentReport.objects.create(**data)

    def _submit_incident(self, title="Forklift near miss"):
        self.client.force_login(self.employee_user)
        return self.client.post(reverse("portal:incident_new"), self._incident_payload(title))

    def test_direct_incident_model_create_does_not_create_surprise_notifications(self):
        self._create_incident()

        self.assertFalse(Notification.objects.exists())

    @patch("licenses.middleware.is_license_active", return_value=True)
    def test_employee_portal_incident_submission_notifies_authorized_company_users_only(self, _mock_license):
        response = self._submit_incident()

        self.assertEqual(response.status_code, 302)
        incident = IncidentReport.objects.get(title="Forklift near miss")
        recipients = set(
            Notification.objects
            .filter(notification_type=Notification.TYPE_INCIDENT_REPORT)
            .values_list("recipient__username", flat=True)
        )
        self.assertEqual(
            recipients,
            {
                "incident_owner",
                "incident_company_admin",
                "incident_hr",
                "incident_attendance",
                "incident_root",
            },
        )
        self.assertNotIn("incident_viewer", recipients)
        self.assertNotIn("incident_other_hr", recipients)

        notification = Notification.objects.get(
            recipient=self.hr,
            notification_type=Notification.TYPE_INCIDENT_REPORT,
        )
        self.assertFalse(notification.is_read)
        self.assertEqual(notification.company, self.company)
        self.assertEqual(notification.content_object, incident)
        self.assertEqual(notification.title, "New incident report")
        self.assertIn("Forklift near miss", notification.message)
        self.assertEqual(
            notification.target_url,
            reverse("incident_reports:detail", args=[incident.pk]),
        )

    def test_incident_report_appears_in_main_panel_list_and_detail(self):
        incident = self._create_incident()
        other_employee = _make_employee(
            self.other_company,
            _make_user("other_incident_employee"),
            "OTHER-INC",
        )
        IncidentReport.objects.create(
            company=self.other_company,
            employee=other_employee,
            incident_date=datetime.date(2026, 6, 16),
            title="Other company incident",
            description="Out of scope.",
            location="Other site",
        )

        self.client.force_login(self.hr)
        list_response = self.client.get(reverse("incident_reports:list"))

        self.assertEqual(list_response.status_code, 200)
        self.assertContains(list_response, "Forklift near miss")
        self.assertNotContains(list_response, "Other company incident")
        self.assertContains(list_response, "Reported Date")
        self.assertContains(list_response, "Created At")

        detail_response = self.client.get(reverse("incident_reports:detail", args=[incident.pk]))
        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(detail_response, "Forklift near miss")
        self.assertContains(detail_response, "Review Action")

    def test_incident_report_list_filters_by_company_employee_status_and_date_range(self):
        submitted = self._create_incident(title="Submitted incident")
        resolved = self._create_incident(
            title="Resolved incident",
            status="resolved",
            incident_date=datetime.date(2026, 6, 20),
        )

        self.client.force_login(self.hr)
        response = self.client.get(reverse("incident_reports:list"), {
            "company": str(self.company.pk),
            "employee": str(self.employee.pk),
            "status": "resolved",
            "start_date": "2026-06-18",
            "end_date": "2026-06-30",
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, resolved.title)
        self.assertNotContains(response, submitted.title)

    def test_attendance_officer_can_access_main_incident_reports(self):
        self._create_incident()

        self.client.force_login(self.attendance)
        response = self.client.get(reverse("incident_reports:list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Forklift near miss")

    def test_employee_cannot_access_main_incident_report_management_page(self):
        self.client.force_login(self.employee_user)

        response = self.client.get(reverse("incident_reports:list"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("portal:dashboard"))

    @patch("licenses.middleware.is_license_active", return_value=True)
    def test_incident_detail_post_updates_status_notes_and_reviewer(self, _mock_license):
        incident = self._create_incident()

        self.client.force_login(self.hr)
        response = self.client.post(reverse("incident_reports:detail", args=[incident.pk]), {
            "status": "resolved",
            "admin_notes": "Reviewed and closed.",
        })

        self.assertRedirects(response, reverse("incident_reports:list"))
        incident.refresh_from_db()
        self.assertEqual(incident.status, "resolved")
        self.assertEqual(incident.admin_notes, "Reviewed and closed.")
        self.assertEqual(incident.reviewed_by, self.hr)
        self.assertIsNotNone(incident.reviewed_at)

    @patch("licenses.middleware.is_license_active", return_value=True)
    def test_opening_incident_detail_marks_only_current_users_notification_read(self, _mock_license):
        self._submit_incident()
        incident = IncidentReport.objects.get(title="Forklift near miss")

        self.client.force_login(self.hr)
        response = self.client.get(reverse("incident_reports:detail", args=[incident.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            Notification.objects.get(
                recipient=self.hr,
                notification_type=Notification.TYPE_INCIDENT_REPORT,
            ).is_read
        )
        self.assertFalse(
            Notification.objects.get(
                recipient=self.attendance,
                notification_type=Notification.TYPE_INCIDENT_REPORT,
            ).is_read
        )

    @patch("licenses.middleware.is_license_active", return_value=True)
    def test_sidebar_count_and_unread_api_are_per_current_user(self, _mock_license):
        self._submit_incident()

        self.client.force_login(self.hr)
        dashboard = self.client.get(reverse("dashboard_home"))
        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(dashboard.context["unread_incident_count"], 1)
        self.assertContains(dashboard, "sidebarIncidentReportBadge")

        response = self.client.get(reverse("notifications:unread_api"))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total_unread"], 1)
        self.assertEqual(payload["incident_report_count"], 1)
        self.assertEqual(payload["latest"][0]["type"], Notification.TYPE_INCIDENT_REPORT)
        self.assertEqual(payload["latest"][0]["title"], "New incident report")

    def test_incident_tabs_show_status_categories_and_history(self):
        submitted = self._create_incident(title="Submitted incident")
        under_review = self._create_incident(
            title="Under review incident",
            status="under_review",
        )
        resolved = self._create_incident(title="Resolved incident", status="resolved")
        rejected = self._create_incident(title="Rejected incident", status="rejected")

        self.client.force_login(self.hr)
        under_review_response = self.client.get(
            reverse("incident_reports:list") + "?tab=under_review"
        )
        history_response = self.client.get(reverse("incident_reports:list") + "?tab=history")

        self.assertContains(under_review_response, under_review.title)
        self.assertNotContains(under_review_response, submitted.title)
        self.assertContains(history_response, resolved.title)
        self.assertContains(history_response, rejected.title)
        self.assertNotContains(history_response, submitted.title)
        self.assertContains(history_response, "Delete selected")

    @patch("licenses.middleware.is_license_active", return_value=True)
    def test_incident_history_bulk_delete_removes_only_closed_scoped_reports(self, _mock_license):
        resolved = self._create_incident(title="Resolved incident", status="resolved")
        under_review = self._create_incident(
            title="Under review incident",
            status="under_review",
        )
        other_employee = _make_employee(
            self.other_company,
            _make_user("delete_other_incident_employee"),
            "OTHER-DEL",
        )
        other_resolved = IncidentReport.objects.create(
            company=self.other_company,
            employee=other_employee,
            incident_date=datetime.date(2026, 6, 16),
            title="Other resolved incident",
            description="Out of scope.",
            location="Other site",
            status="resolved",
        )
        Notification.objects.create(
            recipient=self.hr,
            company=self.company,
            notification_type=Notification.TYPE_INCIDENT_REPORT,
            title="Old incident",
            message="Old incident.",
            content_type=ContentType.objects.get_for_model(resolved, for_concrete_model=False),
            object_id=resolved.pk,
        )

        self.client.force_login(self.hr)
        response = self.client.post(reverse("incident_reports:list") + "?tab=history", {
            "action": "delete_selected",
            "selected_ids": [
                str(resolved.pk),
                str(under_review.pk),
                str(other_resolved.pk),
            ],
        })

        self.assertRedirects(
            response,
            reverse("incident_reports:list") + "?tab=history",
            fetch_redirect_response=False,
        )
        self.assertFalse(IncidentReport.objects.filter(pk=resolved.pk).exists())
        self.assertTrue(IncidentReport.objects.filter(pk=under_review.pk).exists())
        self.assertTrue(IncidentReport.objects.filter(pk=other_resolved.pk).exists())
        self.assertFalse(Notification.objects.filter(object_id=resolved.pk).exists())

    @patch("licenses.middleware.is_license_active", return_value=True)
    def test_incident_delete_is_ignored_outside_history_tab(self, _mock_license):
        rejected = self._create_incident(title="Rejected incident", status="rejected")

        self.client.force_login(self.hr)
        response = self.client.post(reverse("incident_reports:list") + "?tab=rejected", {
            "action": "delete_selected",
            "selected_ids": [str(rejected.pk)],
        })

        self.assertEqual(response.status_code, 302)
        self.assertTrue(IncidentReport.objects.filter(pk=rejected.pk).exists())


class PortalDraftPayslipVisibilityTests(TestCase):
    """Draft payroll must stay hidden from the employee portal."""

    def setUp(self):
        self.company = _make_company("Draft Co")
        self.user = _make_user("draft_emp")
        self.employee = _make_employee(self.company, self.user, "EMP-D")
        self.period_draft = PayrollPeriod.objects.create(
            company=self.company,
            name="June 1-15 2026",
            start_date=datetime.date(2026, 6, 1),
            end_date=datetime.date(2026, 6, 15),
        )
        self.period_approved = PayrollPeriod.objects.create(
            company=self.company,
            name="June 16-30 2026",
            start_date=datetime.date(2026, 6, 16),
            end_date=datetime.date(2026, 6, 30),
        )
        self.draft = PayrollRecord.objects.create(
            company=self.company, payroll_period=self.period_draft, employee=self.employee,
            net_pay=10000, gross_pay=12000, basic_pay=11000,
            daily_rate=1000, hourly_rate=125, status='draft',
        )
        self.approved = PayrollRecord.objects.create(
            company=self.company, payroll_period=self.period_approved, employee=self.employee,
            net_pay=9000, gross_pay=11000, basic_pay=10000,
            daily_rate=1000, hourly_rate=125, status='approved',
        )
        self.client.login(username="draft_emp", password="testpass123")

    def test_draft_payslip_hidden_from_list(self):
        response = self.client.get(reverse("portal:payslip_list"))
        pks = {ps.pk for ps in response.context["payslips"]}
        self.assertIn(self.approved.pk, pks)
        self.assertNotIn(self.draft.pk, pks)

    def test_draft_payslip_detail_returns_404(self):
        response = self.client.get(reverse("portal:payslip_detail", args=[self.draft.pk]))
        self.assertEqual(response.status_code, 404)

    def test_approved_payslip_detail_visible(self):
        response = self.client.get(reverse("portal:payslip_detail", args=[self.approved.pk]))
        self.assertEqual(response.status_code, 200)

    def test_draft_payslip_hidden_from_dashboard(self):
        response = self.client.get(reverse("portal:dashboard"))
        pks = {ps.pk for ps in response.context["recent_payslips"]}
        self.assertIn(self.approved.pk, pks)
        self.assertNotIn(self.draft.pk, pks)
