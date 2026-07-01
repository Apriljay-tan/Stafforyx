import datetime
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from accounts.models import UserCompanyAccess, UserProfile
from companies.models import Company
from employees.models import Employee
from messaging.services import get_or_create_admin_support_conversation, send_message


def _make_company(name='Acme'):
    return Company.objects.create(name=name, email=f'{name.lower()}@test.local')


def _make_user(username, password='testpass123', is_superuser=False):
    if is_superuser:
        return User.objects.create_superuser(username=username, password=password)
    return User.objects.create_user(username=username, password=password)


def _grant_access(user, company):
    UserCompanyAccess.objects.create(user=user, company=company, role='hr_admin', is_active=True)


def _make_chat_admin(username, company):
    user = _make_user(username)
    UserProfile.objects.create(user=user, can_manage_chat=True, role='hr_admin')
    _grant_access(user, company)
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


class AdminMessagingViewTests(TestCase):
    def setUp(self):
        self.company = _make_company()
        self.admin = _make_chat_admin('chat_admin', self.company)
        self.no_chat_user = _make_user('no_chat')
        UserProfile.objects.create(user=self.no_chat_user, can_manage_employees=True, role='hr_admin')
        _grant_access(self.no_chat_user, self.company)
        self.emp_user = _make_user('emp_user')
        self.employee = _make_employee(self.company, user=self.emp_user)
        self.conversation, _ = get_or_create_admin_support_conversation(self.admin, self.employee)

    def test_anonymous_redirects_to_login(self):
        response = self.client.get(reverse('messaging:inbox'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_user_without_can_manage_chat_gets_403(self):
        self.client.login(username='no_chat', password='testpass123')
        response = self.client.get(reverse('messaging:inbox'))
        self.assertEqual(response.status_code, 403)

    def test_chat_manager_gets_200_on_inbox(self):
        self.client.login(username='chat_admin', password='testpass123')
        response = self.client.get(reverse('messaging:inbox'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Messages')

    def test_chat_manager_can_open_thread(self):
        self.client.login(username='chat_admin', password='testpass123')
        response = self.client.get(reverse('messaging:thread', args=[self.conversation.pk]))
        self.assertEqual(response.status_code, 200)

    def test_chat_manager_can_open_compose(self):
        self.client.login(username='chat_admin', password='testpass123')
        response = self.client.get(reverse('messaging:compose'))
        self.assertEqual(response.status_code, 200)

    def test_chat_manager_can_open_audit_list(self):
        self.client.login(username='chat_admin', password='testpass123')
        response = self.client.get(reverse('messaging:audit_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Chat Audit')

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_post_send_message_in_admin_support_thread(self, _mock):
        self.client.login(username='chat_admin', password='testpass123')
        response = self.client.post(reverse('messaging:thread', args=[self.conversation.pk]), {
            'body': 'Hello from admin view',
        })
        self.assertEqual(response.status_code, 302)
        self.conversation.refresh_from_db()
        self.assertTrue(self.conversation.messages.filter(body='Hello from admin view').exists())

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_compose_admin_support_redirects_to_thread(self, _mock):
        other_user = _make_user('emp2')
        other_employee = _make_employee(self.company, user=other_user, employee_id='E002')
        self.client.login(username='chat_admin', password='testpass123')
        response = self.client.post(reverse('messaging:compose'), {
            'compose_type': 'admin_support',
            'employee_id': other_employee.pk,
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith('/messaging/'))

    def test_unread_api_returns_json(self):
        send_message(self.conversation, self.admin, 'Ping')
        self.client.login(username='chat_admin', password='testpass123')
        response = self.client.get(reverse('messaging:unread_api'))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn('total_unread', payload)
        self.assertIn('conversations', payload)

    def test_no_chat_user_cannot_access_audit(self):
        self.client.login(username='no_chat', password='testpass123')
        response = self.client.get(reverse('messaging:audit_list'))
        self.assertEqual(response.status_code, 403)
