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
from notifications.models import Notification


class PortalRequestNotificationTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='Notify Co')
        self.other_company = Company.objects.create(name='Other Co')
        self.employee_user = User.objects.create_user('employee', password='pw')
        self.employee = Employee.objects.create(
            company=self.company,
            user=self.employee_user,
            employee_id='N001',
            first_name='Nora',
            last_name='Requester',
            date_hired=datetime.date(2024, 1, 1),
            status='active',
            overtime_policy='request_required',
        )
        self.leave_type = LeaveType.objects.create(
            company=self.company,
            name='Vacation',
            default_days=5,
        )
        self.admin = self._authorized_user(
            'admin',
            self.company,
            role='company_admin',
            can_manage_leaves=True,
            can_manage_employees=True,
            can_manage_payroll=True,
        )
        self.hr = self._authorized_user(
            'hr',
            self.company,
            role='hr_admin',
            can_manage_leaves=True,
            can_manage_employees=True,
        )
        self.payroll = self._authorized_user(
            'payroll',
            self.company,
            role='payroll_officer',
            can_manage_payroll=True,
        )
        self.attendance = self._authorized_user(
            'attendance',
            self.company,
            role='attendance_officer',
            can_manage_employees=True,
        )
        self.viewer = self._authorized_user('viewer', self.company, role='viewer')
        self.out_of_scope_hr = self._authorized_user(
            'other-hr',
            self.other_company,
            role='hr_admin',
            can_manage_leaves=True,
            can_manage_employees=True,
            can_manage_payroll=True,
        )
        self.superuser = User.objects.create_superuser('root', 'root@example.com', 'pw')
        self.client.force_login(self.employee_user)

    def _authorized_user(self, username, company, role, **profile_flags):
        user = User.objects.create_user(username, password='pw')
        profile = UserProfile.objects.create(
            user=user,
            role='hr_admin' if role != 'viewer' else 'manager',
            is_active_stafforyx=True,
            **profile_flags,
        )
        if role == 'viewer':
            profile.role = 'manager'
            profile.save(update_fields=['role'])
        UserCompanyAccess.objects.create(
            user=user,
            company=company,
            role=role,
            is_active=True,
        )
        return user

    def _recipients_for(self, notification_type):
        return set(
            Notification.objects
            .filter(notification_type=notification_type)
            .values_list('recipient__username', flat=True)
        )

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_leave_portal_submission_notifies_leave_handlers(self, _mock_license):
        response = self.client.post(reverse('portal:leave_new'), {
            'leave_type': str(self.leave_type.pk),
            'start_date': '2026-07-01',
            'end_date': '2026-07-02',
            'reason': 'Family trip',
        })

        self.assertEqual(response.status_code, 302)
        leave = LeaveRequest.objects.get(employee=self.employee)
        recipients = self._recipients_for(Notification.TYPE_LEAVE_REQUEST)
        self.assertEqual(recipients, {'admin', 'hr', 'root'})
        notification = Notification.objects.get(
            recipient=self.admin,
            notification_type=Notification.TYPE_LEAVE_REQUEST,
        )
        self.assertFalse(notification.is_read)
        self.assertEqual(notification.company, self.company)
        self.assertEqual(notification.content_object, leave)
        self.assertEqual(
            notification.target_url,
            reverse('leaves:leave_request_edit', args=[leave.pk]),
        )

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_overtime_portal_submission_notifies_overtime_handlers(self, _mock_license):
        response = self.client.post(reverse('portal:overtime_new'), {
            'date': '2026-07-03',
            'requested_hours': '2.00',
            'reason': 'Inventory count',
        })

        self.assertEqual(response.status_code, 302)
        overtime = OvertimeRequest.objects.get(employee=self.employee)
        recipients = self._recipients_for(Notification.TYPE_OVERTIME_REQUEST)
        self.assertEqual(recipients, {'admin', 'hr', 'attendance', 'root'})
        notification = Notification.objects.get(
            recipient=self.attendance,
            notification_type=Notification.TYPE_OVERTIME_REQUEST,
        )
        self.assertEqual(notification.content_object, overtime)
        self.assertEqual(
            notification.target_url,
            reverse('overtime:manage_overtime_detail', args=[overtime.pk]),
        )

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_cash_advance_portal_submission_notifies_ca_handlers(self, _mock_license):
        response = self.client.post(reverse('portal:ca_new'), {
            'amount': '1250.00',
            'reason': 'Emergency expense',
            'requested_release_date': '2026-07-05',
        })

        self.assertEqual(response.status_code, 302)
        ca = CashAdvanceRequest.objects.get(employee=self.employee)
        recipients = self._recipients_for(Notification.TYPE_CASH_ADVANCE_REQUEST)
        self.assertEqual(recipients, {'admin', 'hr', 'payroll', 'root'})
        notification = Notification.objects.get(
            recipient=self.payroll,
            notification_type=Notification.TYPE_CASH_ADVANCE_REQUEST,
        )
        self.assertEqual(notification.content_object, ca)
        self.assertEqual(
            notification.target_url,
            reverse('cash_advance:manage_ca_detail', args=[ca.pk]),
        )

    def test_direct_model_create_does_not_create_surprise_notifications(self):
        LeaveRequest.objects.create(
            company=self.company,
            employee=self.employee,
            leave_type=self.leave_type,
            start_date=datetime.date(2026, 7, 1),
            end_date=datetime.date(2026, 7, 1),
            total_days=Decimal('1.0'),
            reason='Created outside the portal',
            status='pending',
        )
        OvertimeRequest.objects.create(
            company=self.company,
            employee=self.employee,
            date=datetime.date(2026, 7, 2),
            requested_hours=Decimal('1.00'),
            reason='Created outside the portal',
            status='pending',
            source='employee',
        )
        CashAdvanceRequest.objects.create(
            company=self.company,
            employee=self.employee,
            amount=Decimal('500.00'),
            reason='Created outside the portal',
            status=CashAdvanceRequest.STATUS_PENDING,
        )

        self.assertFalse(Notification.objects.exists())
