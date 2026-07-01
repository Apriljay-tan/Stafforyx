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
from messaging.services import (
    get_or_create_admin_support_conversation,
    get_or_create_direct_conversation,
    send_message,
    unread_count_for_conversation,
    unread_count_for_user,
)


def _make_company(name='Acme'):
    return Company.objects.create(name=name, email=f'{name.lower()}@test.local')


def _make_user(username, password='testpass123'):
    return User.objects.create_user(username=username, password=password)


def _make_chat_admin(username, company):
    user = _make_user(username)
    UserProfile.objects.create(user=user, can_manage_chat=True, role='hr_admin')
    UserCompanyAccess.objects.create(user=user, company=company, role='hr_admin', is_active=True)
    return user


def _make_portal_employee(company, username, employee_id='E001'):
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
        can_use_chat=True,
        user=user,
    )
    company.employee_chat_enabled = True
    company.save(update_fields=['employee_chat_enabled'])
    return user, employee


class AdminThreadPollingApiTests(TestCase):
    def setUp(self):
        self.company = _make_company()
        self.admin = _make_chat_admin('chat_admin', self.company)
        self.emp_user = _make_user('emp_user')
        self.employee = Employee.objects.create(
            company=self.company,
            employee_id='E001',
            first_name='Ana',
            last_name='Reyes',
            email='e001@test.local',
            date_hired=datetime.date(2024, 1, 1),
            status='active',
            can_use_chat=True,
            user=self.emp_user,
        )
        self.company.employee_chat_enabled = True
        self.company.save(update_fields=['employee_chat_enabled'])
        self.conversation, _ = get_or_create_admin_support_conversation(self.admin, self.employee)
        send_message(self.conversation, self.admin, 'First message')
        send_message(self.conversation, self.emp_user, 'Reply')

    def test_participant_can_poll_thread(self):
        self.client.login(username='chat_admin', password='testpass123')
        response = self.client.get(reverse('messaging:thread_api', args=[self.conversation.pk]))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('messages', data)
        self.assertEqual(len(data['messages']), 2)
        self.assertIn('is_mine', data['messages'][0])
        self.assertIn('time_display', data['messages'][0])

    def test_thread_api_after_id_returns_only_new_messages(self):
        self.client.login(username='chat_admin', password='testpass123')
        first_id = self.conversation.messages.order_by('pk').first().pk
        response = self.client.get(
            reverse('messaging:thread_api', args=[self.conversation.pk]),
            {'after_id': first_id},
        )
        self.assertEqual(response.status_code, 200)
        messages = response.json()['messages']
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]['body'], 'Reply')

    def test_non_participant_cannot_poll_thread(self):
        user = _make_user('no_chat')
        UserProfile.objects.create(user=user, role='hr_admin')
        UserCompanyAccess.objects.create(user=user, company=self.company, role='hr_admin', is_active=True)
        self.client.login(username='no_chat', password='testpass123')
        response = self.client.get(reverse('messaging:thread_api', args=[self.conversation.pk]))
        self.assertEqual(response.status_code, 403)

    def test_thread_poll_marks_conversation_read(self):
        send_message(self.conversation, self.emp_user, 'Unread for admin')
        self.client.login(username='chat_admin', password='testpass123')
        self.assertGreater(unread_count_for_conversation(self.conversation, self.admin), 0)
        response = self.client.get(reverse('messaging:thread_api', args=[self.conversation.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(unread_count_for_conversation(self.conversation, self.admin), 0)


class AdminUnreadPollingApiTests(TestCase):
    def setUp(self):
        self.company = _make_company()
        self.admin = _make_chat_admin('chat_admin', self.company)
        self.emp_user = _make_user('emp_user')
        self.employee = Employee.objects.create(
            company=self.company,
            employee_id='E001',
            first_name='Ana',
            last_name='Reyes',
            email='e001@test.local',
            date_hired=datetime.date(2024, 1, 1),
            status='active',
            can_use_chat=True,
            user=self.emp_user,
        )
        self.company.employee_chat_enabled = True
        self.company.save(update_fields=['employee_chat_enabled'])
        self.conversation, _ = get_or_create_admin_support_conversation(self.admin, self.employee)

    def test_unread_api_reflects_new_messages(self):
        send_message(self.conversation, self.emp_user, 'New ping')
        self.client.login(username='chat_admin', password='testpass123')
        response = self.client.get(reverse('messaging:unread_api'))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertGreaterEqual(data['total_unread'], 1)
        conv_entry = next(c for c in data['conversations'] if c['id'] == self.conversation.pk)
        self.assertGreaterEqual(conv_entry['unread'], 1)
        self.assertIn('New ping', conv_entry['preview'])

    def test_unread_api_requires_chat_manager(self):
        user = _make_user('no_chat')
        UserProfile.objects.create(user=user, role='hr_admin')
        UserCompanyAccess.objects.create(user=user, company=self.company, role='hr_admin', is_active=True)
        self.client.login(username='no_chat', password='testpass123')
        response = self.client.get(reverse('messaging:unread_api'))
        self.assertEqual(response.status_code, 403)


class PortalThreadPollingApiTests(TestCase):
    def setUp(self):
        self.company = _make_company()
        self.admin = _make_chat_admin('chat_admin', self.company)
        self.emp_user, self.employee = _make_portal_employee(self.company, 'portal_emp')
        self.peer_user, self.peer = _make_portal_employee(self.company, 'portal_peer', employee_id='E002')
        self.conversation, _ = get_or_create_admin_support_conversation(self.admin, self.employee)
        send_message(self.conversation, self.admin, 'Support hello')

    def test_employee_can_poll_own_thread(self):
        self.client.login(username='portal_emp', password='testpass123')
        response = self.client.get(reverse('portal:messages_thread_api', args=[self.conversation.pk]))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data['messages']), 1)
        self.assertEqual(data['messages'][0]['sender_display'], 'HR Support')

    def test_employee_cannot_poll_other_conversation(self):
        third_user, third_emp = _make_portal_employee(self.company, 'third', employee_id='E003')
        conv = Conversation.objects.create(
            company=self.company,
            conversation_type=TYPE_DIRECT,
            created_by=self.peer_user,
        )
        ConversationParticipant.objects.create(conversation=conv, user=self.peer_user, employee=self.peer)
        ConversationParticipant.objects.create(conversation=conv, user=third_user, employee=third_emp)
        self.client.login(username='portal_emp', password='testpass123')
        response = self.client.get(reverse('portal:messages_thread_api', args=[conv.pk]))
        self.assertEqual(response.status_code, 403)

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_portal_unread_api_updates_after_message(self, _mock):
        send_message(self.conversation, self.admin, 'Another update')
        self.client.login(username='portal_emp', password='testpass123')
        before = unread_count_for_user(self.emp_user)
        response = self.client.get(reverse('portal:messages_unread_api'))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['total_unread'], before)
        entry = next(c for c in data['conversations'] if c['id'] == self.conversation.pk)
        self.assertGreaterEqual(entry['unread'], 1)

    def test_disabled_employee_cannot_poll(self):
        self.employee.can_use_chat = False
        self.employee.save(update_fields=['can_use_chat'])
        self.client.login(username='portal_emp', password='testpass123')
        response = self.client.get(reverse('portal:messages_thread_api', args=[self.conversation.pk]))
        self.assertEqual(response.status_code, 403)

    def test_direct_thread_poll_after_id(self):
        conv, _ = get_or_create_direct_conversation(self.emp_user, self.peer_user)
        send_message(conv, self.emp_user, 'Hi peer')
        send_message(conv, self.peer_user, 'Hi back')
        self.client.login(username='portal_emp', password='testpass123')
        first_id = conv.messages.order_by('pk').first().pk
        response = self.client.get(
            reverse('portal:messages_thread_api', args=[conv.pk]),
            {'after_id': first_id},
        )
        self.assertEqual(response.status_code, 200)
        messages = response.json()['messages']
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]['body'], 'Hi back')
        self.assertTrue(messages[0]['is_mine'] is False)
