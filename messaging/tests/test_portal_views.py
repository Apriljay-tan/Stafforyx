import datetime
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from accounts.models import UserCompanyAccess, UserProfile
from companies.models import Company
from employees.models import Employee
from messaging.constants import TYPE_DIRECT
from messaging.models import Conversation, ConversationParticipant
from messaging.permissions import get_support_display_name
from messaging.services import get_or_create_admin_support_conversation, send_message


def _make_company(name='Acme'):
    return Company.objects.create(name=name, email=f'{name.lower()}@test.local')


def _make_user(username, password='testpass123'):
    return User.objects.create_user(username=username, password=password)


def _make_portal_employee(company, username, *, can_use_chat=True, employee_id='E001'):
    user = _make_user(username)
    UserProfile.objects.create(user=user, role='employee')
    employee = Employee.objects.create(
        company=company,
        employee_id=employee_id,
        first_name='Ana',
        last_name='Reyes',
        email=f'{employee_id}@test.local',
        date_hired=datetime.date(2024, 1, 1),
        status='active',
        can_use_chat=can_use_chat,
        user=user,
    )
    company.employee_chat_enabled = True
    company.save(update_fields=['employee_chat_enabled'])
    return user, employee


class PortalMessagingViewTests(TestCase):
    def setUp(self):
        self.company = _make_company()
        self.emp_user, self.employee = _make_portal_employee(self.company, 'portal_emp')
        self.peer_user, self.peer = _make_portal_employee(self.company, 'portal_peer', employee_id='E002')
        self.outsider_user, self.outsider = _make_portal_employee(
            _make_company('OtherCo'),
            'outsider',
            employee_id='E099',
        )
        self.admin = _make_user('chat_admin')
        UserProfile.objects.create(user=self.admin, can_manage_chat=True, role='hr_admin')
        UserCompanyAccess.objects.create(user=self.admin, company=self.company, role='hr_admin', is_active=True)
        self.support_conv, _ = get_or_create_admin_support_conversation(self.admin, self.employee)
        send_message(self.support_conv, self.admin, 'Welcome from support')

    def test_enabled_employee_can_access_inbox(self):
        self.client.login(username='portal_emp', password='testpass123')
        response = self.client.get(reverse('portal:messages_inbox'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Messages')

    def test_disabled_employee_cannot_access_chat(self):
        self.employee.can_use_chat = False
        self.employee.save(update_fields=['can_use_chat'])
        self.client.login(username='portal_emp', password='testpass123')
        response = self.client.get(reverse('portal:messages_inbox'))
        self.assertEqual(response.status_code, 403)

    def test_employee_cannot_open_conversation_not_participant(self):
        third_user, third_employee = _make_portal_employee(self.company, 'third_emp', employee_id='E003')
        conv = Conversation.objects.create(
            company=self.company,
            conversation_type=TYPE_DIRECT,
            created_by=self.peer_user,
        )
        ConversationParticipant.objects.create(conversation=conv, user=self.peer_user, employee=self.peer)
        ConversationParticipant.objects.create(conversation=conv, user=third_user, employee=third_employee)
        self.client.login(username='portal_emp', password='testpass123')
        response = self.client.get(reverse('portal:messages_thread', args=[conv.pk]))
        self.assertEqual(response.status_code, 403)

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_employee_cannot_message_out_of_scope_contact(self, _mock):
        self.client.login(username='portal_emp', password='testpass123')
        response = self.client.post(reverse('portal:messages_compose'), {
            'compose_type': 'direct',
            'contact_employee_id': self.outsider.pk,
        })
        self.assertEqual(response.status_code, 404)

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_employee_can_reply_in_existing_conversation(self, _mock):
        self.client.login(username='portal_emp', password='testpass123')
        response = self.client.post(reverse('portal:messages_thread', args=[self.support_conv.pk]), {
            'body': 'Thanks for the help',
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.support_conv.messages.filter(body='Thanks for the help').exists())

    def test_admin_support_persona_displays_to_employee(self):
        support_name = get_support_display_name(self.company)
        self.client.login(username='portal_emp', password='testpass123')
        response = self.client.get(reverse('portal:messages_thread', args=[self.support_conv.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, support_name)
        self.assertNotContains(response, self.admin.get_full_name() or self.admin.username)

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_employee_can_compose_direct_with_allowed_contact(self, _mock):
        self.client.login(username='portal_emp', password='testpass123')
        response = self.client.post(reverse('portal:messages_compose'), {
            'compose_type': 'direct',
            'contact_employee_id': self.peer.pk,
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith('/portal/messages/'))

    def test_unread_api_returns_json(self):
        self.client.login(username='portal_emp', password='testpass123')
        response = self.client.get(reverse('portal:messages_unread_api'))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('total_unread', data)
        self.assertIn('conversations', data)

    def test_thread_api_requires_participation(self):
        conv = Conversation.objects.create(
            company=self.company,
            conversation_type=TYPE_DIRECT,
            created_by=self.peer_user,
        )
        ConversationParticipant.objects.create(conversation=conv, user=self.peer_user)
        ConversationParticipant.objects.create(conversation=conv, user=self.outsider_user)
        self.client.login(username='portal_emp', password='testpass123')
        response = self.client.get(reverse('portal:messages_thread_api', args=[conv.pk]))
        self.assertEqual(response.status_code, 403)
