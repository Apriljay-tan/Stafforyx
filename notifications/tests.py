import datetime
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from accounts.models import UserCompanyAccess, UserProfile
from cash_advance.models import CashAdvanceRequest
from companies.models import Company
from employees.models import Employee
from leaves.models import LeaveRequest, LeaveType
from overtime.models import OvertimeRequest
from portal.models import IncidentReport

from .models import Notification
from .services import create_request_notifications


class NotificationReadStateTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='Read Co')
        self.other_company = Company.objects.create(name='Other Read Co')
        self.employee = Employee.objects.create(
            company=self.company,
            employee_id='R001',
            first_name='Rhea',
            last_name='Reader',
            date_hired=datetime.date(2024, 1, 1),
            status='active',
        )
        self.leave_type = LeaveType.objects.create(
            company=self.company,
            name='Sick Leave',
            default_days=5,
        )
        self.leave = LeaveRequest.objects.create(
            company=self.company,
            employee=self.employee,
            leave_type=self.leave_type,
            start_date=datetime.date(2026, 7, 1),
            end_date=datetime.date(2026, 7, 1),
            total_days=Decimal('1.0'),
            reason='Medical appointment',
        )
        self.overtime = OvertimeRequest.objects.create(
            company=self.company,
            employee=self.employee,
            date=datetime.date(2026, 7, 2),
            requested_hours=Decimal('2.00'),
            reason='Inventory',
            source='employee',
        )
        self.ca = CashAdvanceRequest.objects.create(
            company=self.company,
            employee=self.employee,
            amount=Decimal('1000.00'),
            reason='Emergency',
        )
        self.incident = IncidentReport.objects.create(
            company=self.company,
            employee=self.employee,
            incident_date=datetime.date(2026, 7, 4),
            title='Warehouse near miss',
            description='A pallet nearly fell from a rack.',
            location='Warehouse',
        )
        self.admin = self._manager(
            'admin',
            role='company_admin',
            can_access_dashboard=True,
            can_manage_leaves=True,
            can_manage_employees=True,
            can_manage_payroll=True,
        )
        self.hr = self._manager(
            'hr',
            role='hr_admin',
            can_access_dashboard=True,
            can_manage_leaves=True,
            can_manage_employees=True,
        )

    def _manager(self, username, role, **profile_flags):
        user = User.objects.create_user(username, password='pw')
        UserProfile.objects.create(
            user=user,
            role='hr_admin',
            is_active_stafforyx=True,
            **profile_flags,
        )
        UserCompanyAccess.objects.create(
            user=user,
            company=self.company,
            role=role,
            is_active=True,
        )
        return user

    def _notify(self, obj, notification_type, target):
        return create_request_notifications(
            obj,
            notification_type,
            'New request',
            'A request needs review.',
            target,
        )

    def test_dashboard_context_exposes_total_and_module_unread_counts(self):
        self._notify(
            self.leave,
            Notification.TYPE_LEAVE_REQUEST,
            reverse('leaves:leave_request_edit', args=[self.leave.pk]),
        )
        self._notify(
            self.overtime,
            Notification.TYPE_OVERTIME_REQUEST,
            reverse('overtime:manage_overtime_detail', args=[self.overtime.pk]),
        )
        self._notify(
            self.ca,
            Notification.TYPE_CASH_ADVANCE_REQUEST,
            reverse('cash_advance:manage_ca_detail', args=[self.ca.pk]),
        )
        self._notify(
            self.incident,
            Notification.TYPE_INCIDENT_REPORT,
            reverse('incident_reports:detail', args=[self.incident.pk]),
        )

        self.client.force_login(self.admin)
        response = self.client.get(reverse('dashboard_home'))

        self.assertEqual(response.context['notification_unread_total'], 4)
        self.assertEqual(response.context['unread_leave_count'], 1)
        self.assertEqual(response.context['unread_overtime_count'], 1)
        self.assertEqual(response.context['unread_ca_count'], 1)
        self.assertEqual(response.context['unread_incident_count'], 1)
        self.assertContains(response, 'View all notifications')
        self.assertContains(response, 'CA Requests')
        self.assertContains(response, 'Incident Reports')

    def test_opening_leave_list_marks_only_current_users_leave_notifications_read(self):
        self._notify(
            self.leave,
            Notification.TYPE_LEAVE_REQUEST,
            reverse('leaves:leave_request_edit', args=[self.leave.pk]),
        )

        self.client.force_login(self.admin)
        response = self.client.get(reverse('leaves:leave_request_list'))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            Notification.objects.get(
                recipient=self.admin,
                notification_type=Notification.TYPE_LEAVE_REQUEST,
            ).is_read
        )
        self.assertFalse(
            Notification.objects.get(
                recipient=self.hr,
                notification_type=Notification.TYPE_LEAVE_REQUEST,
            ).is_read
        )

    def test_opening_overtime_detail_marks_only_current_users_matching_notification_read(self):
        self._notify(
            self.overtime,
            Notification.TYPE_OVERTIME_REQUEST,
            reverse('overtime:manage_overtime_detail', args=[self.overtime.pk]),
        )

        self.client.force_login(self.admin)
        response = self.client.get(reverse('overtime:manage_overtime_detail', args=[self.overtime.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            Notification.objects.get(
                recipient=self.admin,
                notification_type=Notification.TYPE_OVERTIME_REQUEST,
            ).is_read
        )
        self.assertFalse(
            Notification.objects.get(
                recipient=self.hr,
                notification_type=Notification.TYPE_OVERTIME_REQUEST,
            ).is_read
        )

    def test_notification_open_view_marks_one_notification_read_and_redirects(self):
        self._notify(
            self.ca,
            Notification.TYPE_CASH_ADVANCE_REQUEST,
            reverse('cash_advance:manage_ca_detail', args=[self.ca.pk]),
        )
        notification = Notification.objects.get(
            recipient=self.admin,
            notification_type=Notification.TYPE_CASH_ADVANCE_REQUEST,
        )

        self.client.force_login(self.admin)
        response = self.client.get(reverse('notifications:open', args=[notification.pk]))

        self.assertRedirects(
            response,
            reverse('cash_advance:manage_ca_detail', args=[self.ca.pk]),
            fetch_redirect_response=False,
        )
        notification.refresh_from_db()
        self.assertTrue(notification.is_read)

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_mark_all_read_updates_bell_count_for_current_user_only(self, _mock_license):
        self._notify(
            self.leave,
            Notification.TYPE_LEAVE_REQUEST,
            reverse('leaves:leave_request_edit', args=[self.leave.pk]),
        )
        self._notify(
            self.overtime,
            Notification.TYPE_OVERTIME_REQUEST,
            reverse('overtime:manage_overtime_detail', args=[self.overtime.pk]),
        )

        self.client.force_login(self.admin)
        response = self.client.post(reverse('notifications:mark_all_read'))

        self.assertRedirects(response, reverse('notifications:list'))
        self.assertEqual(Notification.objects.filter(recipient=self.admin, is_read=False).count(), 0)
        self.assertEqual(Notification.objects.filter(recipient=self.hr, is_read=False).count(), 2)

    def test_employee_portal_does_not_show_admin_notification_bell(self):
        employee_user = User.objects.create_user('employee-only', password='pw')
        self.employee.user = employee_user
        self.employee.save(update_fields=['user'])
        UserProfile.objects.create(
            user=employee_user,
            role='employee',
            employee=self.employee,
            company=self.company,
            is_active_stafforyx=True,
        )

        self.client.force_login(employee_user)
        response = self.client.get(reverse('portal:dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'View all notifications')

    def test_unread_api_returns_only_current_user_notifications(self):
        self._notify(
            self.leave,
            Notification.TYPE_LEAVE_REQUEST,
            reverse('leaves:leave_request_edit', args=[self.leave.pk]),
        )
        Notification.objects.create(
            recipient=self.hr,
            company=self.company,
            notification_type=Notification.TYPE_SYSTEM,
            title='HR only',
            message='Visible only to HR.',
            target_url='/notifications/',
        )

        self.client.force_login(self.admin)
        response = self.client.get(reverse('notifications:unread_api'))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['total_unread'], 1)
        self.assertEqual(len(payload['latest']), 1)
        self.assertEqual(payload['latest'][0]['type'], Notification.TYPE_LEAVE_REQUEST)

    def test_unread_api_includes_total_and_per_module_counts(self):
        self._notify(
            self.leave,
            Notification.TYPE_LEAVE_REQUEST,
            reverse('leaves:leave_request_edit', args=[self.leave.pk]),
        )
        self._notify(
            self.overtime,
            Notification.TYPE_OVERTIME_REQUEST,
            reverse('overtime:manage_overtime_detail', args=[self.overtime.pk]),
        )
        self._notify(
            self.ca,
            Notification.TYPE_CASH_ADVANCE_REQUEST,
            reverse('cash_advance:manage_ca_detail', args=[self.ca.pk]),
        )
        self._notify(
            self.incident,
            Notification.TYPE_INCIDENT_REPORT,
            reverse('incident_reports:detail', args=[self.incident.pk]),
        )

        self.client.force_login(self.admin)
        response = self.client.get(reverse('notifications:unread_api'))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['total_unread'], 4)
        self.assertEqual(payload['leave_count'], 1)
        self.assertEqual(payload['overtime_count'], 1)
        self.assertEqual(payload['cash_advance_count'], 1)
        self.assertEqual(payload['incident_report_count'], 1)
        self.assertEqual(len(payload['latest']), 4)
        self.assertIn('created_display', payload['latest'][0])
        self.assertTrue(payload['latest'][0]['url'].startswith('/notifications/'))

    def test_unread_api_does_not_mark_notifications_read(self):
        self._notify(
            self.leave,
            Notification.TYPE_LEAVE_REQUEST,
            reverse('leaves:leave_request_edit', args=[self.leave.pk]),
        )
        notification = Notification.objects.get(
            recipient=self.admin,
            notification_type=Notification.TYPE_LEAVE_REQUEST,
        )

        self.client.force_login(self.admin)
        response = self.client.get(reverse('notifications:unread_api'))

        self.assertEqual(response.status_code, 200)
        notification.refresh_from_db()
        self.assertFalse(notification.is_read)
        self.assertIsNone(notification.read_at)

    def test_unread_api_requires_authorized_user(self):
        anonymous_response = self.client.get(reverse('notifications:unread_api'))
        self.assertEqual(anonymous_response.status_code, 302)

        employee_user = User.objects.create_user('employee-api', password='pw')
        UserProfile.objects.create(
            user=employee_user,
            role='employee',
            employee=self.employee,
            company=self.company,
            is_active_stafforyx=True,
        )
        self.client.force_login(employee_user)
        employee_response = self.client.get(reverse('notifications:unread_api'))

        self.assertIn(employee_response.status_code, (302, 403))

    def test_unread_api_respects_company_scoping(self):
        self._notify(
            self.leave,
            Notification.TYPE_LEAVE_REQUEST,
            reverse('leaves:leave_request_edit', args=[self.leave.pk]),
        )
        Notification.objects.create(
            recipient=self.admin,
            company=self.other_company,
            notification_type=Notification.TYPE_SYSTEM,
            title='Out of scope',
            message='This company is not assigned to admin.',
            target_url='/notifications/',
        )

        self.client.force_login(self.admin)
        response = self.client.get(reverse('notifications:unread_api'))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['total_unread'], 1)
        self.assertEqual(payload['latest'][0]['title'], 'New request')
