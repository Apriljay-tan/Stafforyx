import datetime

from django.contrib.auth.models import User
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
