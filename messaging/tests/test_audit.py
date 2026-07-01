import datetime
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import UserCompanyAccess, UserProfile
from companies.models import Company
from employees.models import Employee
from messaging.models import Message
from messaging.services import (
    audit_conversations,
    enrich_audit_messages,
    get_or_create_admin_support_conversation,
    send_message,
    soft_delete_message,
)


def _make_company(name='Acme'):
    return Company.objects.create(name=name, email=f'{name.lower()}@test.local')


def _make_user(username, password='testpass123', is_superuser=False):
    if is_superuser:
        return User.objects.create_superuser(username=username, password=password)
    return User.objects.create_user(username=username, password=password)


def _make_chat_admin(username, company):
    user = _make_user(username)
    UserProfile.objects.create(user=user, can_manage_chat=True, role='hr_admin')
    UserCompanyAccess.objects.create(user=user, company=company, role='hr_admin', is_active=True)
    return user


def _make_employee(company, user=None, employee_id='E001'):
    employee = Employee.objects.create(
        company=company,
        employee_id=employee_id,
        first_name='Ana',
        last_name='Reyes',
        email=f'{employee_id}@test.local',
        date_hired=datetime.date(2024, 1, 1),
        status='active',
        can_use_chat=True,
    )
    company.employee_chat_enabled = True
    company.save(update_fields=['employee_chat_enabled'])
    if user:
        employee.user = user
        employee.save(update_fields=['user'])
    return employee


class AuditAccessTests(TestCase):
    def setUp(self):
        self.company = _make_company()
        self.other_company = _make_company('OtherCo')
        self.admin = _make_chat_admin('chat_admin', self.company)
        self.other_admin = _make_chat_admin('other_admin', self.other_company)
        self.superuser = _make_user('super', is_superuser=True)
        self.emp_user = _make_user('emp_user')
        UserProfile.objects.create(user=self.emp_user, role='employee')
        self.employee = _make_employee(self.company, user=self.emp_user)
        self.conv, _ = get_or_create_admin_support_conversation(self.admin, self.employee)
        send_message(self.conv, self.admin, 'Audit secret phrase')

    def test_superuser_can_access_audit_list(self):
        self.client.login(username='super', password='testpass123')
        response = self.client.get(reverse('messaging:audit_list'))
        self.assertEqual(response.status_code, 200)

    def test_can_manage_chat_user_can_access_audit(self):
        self.client.login(username='chat_admin', password='testpass123')
        response = self.client.get(reverse('messaging:audit_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Audit secret phrase')

    def test_normal_employee_cannot_access_audit(self):
        self.client.login(username='emp_user', password='testpass123')
        response = self.client.get(reverse('messaging:audit_list'))
        self.assertEqual(response.status_code, 403)

    def test_company_scoped_admin_cannot_see_other_company_detail(self):
        self.client.login(username='other_admin', password='testpass123')
        response = self.client.get(reverse('messaging:audit_detail', args=[self.conv.pk]))
        self.assertEqual(response.status_code, 403)

    def test_company_scoped_admin_list_excludes_other_company(self):
        self.client.login(username='other_admin', password='testpass123')
        response = self.client.get(reverse('messaging:audit_list'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Audit secret phrase')


class AuditFilterTests(TestCase):
    def setUp(self):
        self.company = _make_company()
        self.admin = _make_chat_admin('chat_admin', self.company)
        self.emp_user = _make_user('emp_user')
        self.employee = _make_employee(self.company, user=self.emp_user)
        self.conv, _ = get_or_create_admin_support_conversation(self.admin, self.employee)
        send_message(self.conv, self.admin, 'Payroll question about Ana')

    def test_search_by_body_works(self):
        self.client.login(username='chat_admin', password='testpass123')
        response = self.client.get(reverse('messaging:audit_list'), {'q': 'Payroll'})
        self.assertContains(response, 'Payroll question')

    def test_search_by_participant_works(self):
        self.client.login(username='chat_admin', password='testpass123')
        response = self.client.get(reverse('messaging:audit_list'), {'q': 'Ana'})
        self.assertContains(response, 'Payroll question')

    def test_conversation_type_filter_works(self):
        self.client.login(username='chat_admin', password='testpass123')
        response = self.client.get(reverse('messaging:audit_list'), {'type': 'admin_support'})
        self.assertContains(response, 'Payroll question')
        response = self.client.get(reverse('messaging:audit_list'), {'type': 'group'})
        self.assertNotContains(response, 'Payroll question')

    def test_date_filter_excludes_old_conversation(self):
        self.conv.last_message_at = timezone.now() - datetime.timedelta(days=30)
        self.conv.save(update_fields=['last_message_at'])
        self.client.login(username='chat_admin', password='testpass123')
        today = timezone.localdate().isoformat()
        response = self.client.get(reverse('messaging:audit_list'), {
            'date_from': today,
            'date_to': today,
        })
        self.assertNotContains(response, 'Payroll question')


class AuditDetailTests(TestCase):
    def setUp(self):
        self.company = _make_company()
        self.admin = _make_chat_admin('chat_admin', self.company)
        self.emp_user = _make_user('emp_user')
        self.employee = _make_employee(self.company, user=self.emp_user)
        self.conv, _ = get_or_create_admin_support_conversation(self.admin, self.employee)

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_detail_shows_real_sender_identity(self, _mock):
        send_message(self.conv, self.admin, 'HR reply')
        self.client.login(username='chat_admin', password='testpass123')
        response = self.client.get(reverse('messaging:audit_detail', args=[self.conv.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'chat_admin')
        self.assertContains(response, 'Employee sees: HR Support')

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_detail_shows_attachment_metadata(self, _mock):
        photo = SimpleUploadedFile('proof.jpg', b'jpg', content_type='image/jpeg')
        send_message(self.conv, self.admin, 'See photo', attachment=photo)
        self.client.login(username='chat_admin', password='testpass123')
        response = self.client.get(reverse('messaging:audit_detail', args=[self.conv.pk]))
        self.assertContains(response, 'msg-chat-attachment-img')
        self.assertContains(response, 'See photo')

    def test_deleted_message_shows_marker_not_hard_deleted(self):
        msg = send_message(self.conv, self.admin, 'Remove me')
        soft_delete_message(msg, self.admin)
        self.assertTrue(Message.objects.filter(pk=msg.pk).exists())
        enriched = enrich_audit_messages(
            self.conv.messages.filter(pk=msg.pk).prefetch_related('attachments'),
            self.admin,
        )
        self.assertTrue(enriched[0]['is_deleted'])
        self.assertEqual(enriched[0]['body'], 'Remove me')

    def test_csv_export_returns_rows(self):
        send_message(self.conv, self.admin, 'Export me')
        self.client.login(username='chat_admin', password='testpass123')
        response = self.client.get(reverse('messaging:audit_export'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv')
        content = response.content.decode('utf-8')
        self.assertIn('conversation_id', content)
        self.assertIn('Admin Support', content)
