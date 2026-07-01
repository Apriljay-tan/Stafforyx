import datetime

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from accounts.models import UserCompanyAccess, UserProfile
from companies.models import Company
from employees.models import Employee
from messaging.constants import TYPE_ADMIN_SUPPORT, TYPE_DIRECT, TYPE_GROUP
from messaging.models import Conversation, ConversationParticipant, Message
from messaging.permissions import validate_group_participant_users
from messaging.services import (
    archive_conversation,
    create_group_conversation,
    get_or_create_admin_support_conversation,
    get_or_create_direct_conversation,
    inbox_for_user,
    mark_conversation_read,
    send_message,
    serialize_message_for_user,
    soft_delete_message,
    unread_count_for_conversation,
    unread_count_for_user,
)


def _make_company(name, email=None, **kwargs):
    return Company.objects.create(
        name=name,
        email=email or f'{name.lower().replace(" ", "")}@test.local',
        **kwargs,
    )


def _make_user(username, password='testpass123', is_superuser=False):
    if is_superuser:
        return User.objects.create_superuser(username=username, password=password)
    return User.objects.create_user(username=username, password=password)


def _grant_access(user, company, role='viewer'):
    return UserCompanyAccess.objects.create(user=user, company=company, role=role, is_active=True)


_emp_counter = 0


def _make_employee(company, user=None, **kwargs):
    global _emp_counter
    _emp_counter += 1
    defaults = {
        'company': company,
        'employee_id': f'TST{_emp_counter:03d}',
        'first_name': 'Test',
        'last_name': 'Emp',
        'email': f'emp{_emp_counter}@test.local',
        'date_hired': datetime.date(2024, 1, 1),
        'status': 'active',
    }
    defaults.update(kwargs)
    employee = Employee.objects.create(**defaults)
    if user is not None:
        employee.user = user
        employee.save(update_fields=['user'])
    return employee


def _enable_chat(company, employee):
    company.employee_chat_enabled = True
    company.save(update_fields=['employee_chat_enabled'])
    employee.can_use_chat = True
    employee.save(update_fields=['can_use_chat'])


def _make_chat_admin(username, company):
    user = _make_user(username)
    UserProfile.objects.create(user=user, can_manage_chat=True)
    _grant_access(user, company)
    return user


class AdminSupportConversationTests(TestCase):
    def setUp(self):
        self.company = _make_company('Acme')
        self.admin = _make_chat_admin('admin', self.company)
        self.emp_user = _make_user('emp')
        self.employee = _make_employee(self.company, user=self.emp_user)
        _enable_chat(self.company, self.employee)

    def test_creates_new_conversation(self):
        conv, created = get_or_create_admin_support_conversation(self.admin, self.employee)
        self.assertTrue(created)
        self.assertEqual(conv.conversation_type, TYPE_ADMIN_SUPPORT)
        self.assertEqual(conv.participants.filter(user=self.emp_user).count(), 1)

    def test_reuses_existing_thread(self):
        conv1, _ = get_or_create_admin_support_conversation(self.admin, self.employee)
        conv2, created = get_or_create_admin_support_conversation(self.admin, self.employee)
        self.assertFalse(created)
        self.assertEqual(conv1.pk, conv2.pk)


class SendMessageTests(TestCase):
    def setUp(self):
        self.company = _make_company('Acme')
        self.admin = _make_chat_admin('admin', self.company)
        self.emp_user = _make_user('emp')
        self.employee = _make_employee(self.company, user=self.emp_user)
        _enable_chat(self.company, self.employee)
        self.conv, _ = get_or_create_admin_support_conversation(self.admin, self.employee)

    def test_send_message_updates_last_message_at(self):
        msg = send_message(self.conv, self.admin, 'Hello')
        self.conv.refresh_from_db()
        self.assertIsNotNone(self.conv.last_message_at)
        self.assertEqual(self.conv.last_message_at, msg.created_at)

    def test_stores_real_sender_user(self):
        msg = send_message(self.conv, self.admin, 'Hello')
        self.assertEqual(msg.sender_user, self.admin)


class SerializeMessageTests(TestCase):
    def setUp(self):
        self.company = _make_company('Acme')
        self.admin = _make_chat_admin('admin', self.company)
        self.emp_user = _make_user('emp')
        self.employee = _make_employee(
            self.company, user=self.emp_user, first_name='Ana', last_name='Reyes',
        )
        _enable_chat(self.company, self.employee)
        self.conv, _ = get_or_create_admin_support_conversation(self.admin, self.employee)
        self.msg = send_message(self.conv, self.admin, 'Hello from HR')

    def test_employee_sees_persona_on_admin_support(self):
        data = serialize_message_for_user(self.msg, self.emp_user)
        self.assertEqual(data['sender_display'], 'HR Support')
        self.assertNotIn('sender_user_id', data)

    def test_admin_sees_real_sender_name(self):
        data = serialize_message_for_user(self.msg, self.admin)
        self.assertIn(self.admin.username, data['sender_display'])
        self.assertEqual(data['sender_user_id'], self.admin.pk)

    def test_company_persona_override(self):
        self.company.chat_support_display_name = 'Company Desk'
        self.company.save(update_fields=['chat_support_display_name'])
        data = serialize_message_for_user(self.msg, self.emp_user)
        self.assertEqual(data['sender_display'], 'Company Desk')

    def test_employee_message_avatar_hides_admin_photo(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        self.admin.stafforyx_profile.profile_photo = SimpleUploadedFile(
            'admin.png', b'bytes', content_type='image/png',
        )
        self.admin.stafforyx_profile.save(update_fields=['profile_photo'])
        from messaging.views import enrich_chat_messages

        enriched = enrich_chat_messages([self.msg], self.emp_user)
        self.assertIsNone(enriched[0]['sender_avatar']['image_url'])
        self.assertEqual(enriched[0]['sender_avatar']['variant'], 'support')

    def test_admin_message_avatar_shows_admin_photo(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        self.admin.stafforyx_profile.profile_photo = SimpleUploadedFile(
            'admin.png', b'bytes', content_type='image/png',
        )
        self.admin.stafforyx_profile.save(update_fields=['profile_photo'])
        from messaging.views import enrich_chat_messages

        enriched = enrich_chat_messages([self.msg], self.admin)
        self.assertTrue(enriched[0]['sender_avatar']['image_url'])


class SoftDeleteMessageTests(TestCase):
    def setUp(self):
        self.company = _make_company('Acme')
        self.admin = _make_chat_admin('admin', self.company)
        self.emp_user = _make_user('emp')
        self.employee = _make_employee(self.company, user=self.emp_user)
        _enable_chat(self.company, self.employee)
        self.conv, _ = get_or_create_admin_support_conversation(self.admin, self.employee)
        self.msg = send_message(self.conv, self.admin, 'Delete me')

    def test_soft_delete_sets_deleted_at(self):
        soft_delete_message(self.msg, self.admin)
        self.msg.refresh_from_db()
        self.assertIsNotNone(self.msg.deleted_at)
        self.assertEqual(self.msg.deleted_by, self.admin)

    def test_employee_sees_removed_body(self):
        soft_delete_message(self.msg, self.admin)
        data = serialize_message_for_user(self.msg, self.emp_user)
        self.assertEqual(data['body'], '[Message removed]')

    def test_admin_sees_original_body(self):
        soft_delete_message(self.msg, self.admin)
        data = serialize_message_for_user(self.msg, self.admin)
        self.assertEqual(data['body'], 'Delete me')


class UnreadCountTests(TestCase):
    def setUp(self):
        self.company = _make_company('Acme')
        self.admin = _make_chat_admin('admin', self.company)
        self.emp_user = _make_user('emp')
        self.employee = _make_employee(self.company, user=self.emp_user)
        _enable_chat(self.company, self.employee)
        self.conv, _ = get_or_create_admin_support_conversation(self.admin, self.employee)

    def test_unread_counts_other_participants_messages(self):
        send_message(self.conv, self.admin, 'One')
        send_message(self.conv, self.admin, 'Two')
        self.assertEqual(unread_count_for_conversation(self.conv, self.emp_user), 2)
        self.assertEqual(unread_count_for_user(self.emp_user), 2)

    def test_mark_read_clears_unread(self):
        send_message(self.conv, self.admin, 'One')
        mark_conversation_read(self.conv, self.emp_user)
        self.assertEqual(unread_count_for_conversation(self.conv, self.emp_user), 0)
        self.assertEqual(unread_count_for_user(self.emp_user), 0)


class DirectConversationTests(TestCase):
    def setUp(self):
        self.company = _make_company('Acme')
        self.user_a = _make_user('user_a')
        self.user_b = _make_user('user_b')
        self.emp_a = _make_employee(self.company, user=self.user_a, employee_id='A001')
        self.emp_b = _make_employee(
            self.company, user=self.user_b, employee_id='B001', first_name='Bob', last_name='Lee',
        )
        _enable_chat(self.company, self.emp_a)
        _enable_chat(self.company, self.emp_b)

    def test_creates_direct_conversation(self):
        conv, created = get_or_create_direct_conversation(self.user_a, self.user_b)
        self.assertTrue(created)
        self.assertEqual(conv.conversation_type, TYPE_DIRECT)
        self.assertEqual(conv.participants.count(), 2)

    def test_reuses_direct_conversation(self):
        conv1, _ = get_or_create_direct_conversation(self.user_a, self.user_b)
        conv2, created = get_or_create_direct_conversation(self.user_b, self.user_a)
        self.assertFalse(created)
        self.assertEqual(conv1.pk, conv2.pk)


class GroupConversationTests(TestCase):
    def setUp(self):
        self.company = _make_company('Acme')
        self.creator = _make_user('creator')
        self.peer1_user = _make_user('peer1')
        self.peer2_user = _make_user('peer2')
        self.creator_emp = _make_employee(self.company, user=self.creator, employee_id='C001')
        self.peer1 = _make_employee(self.company, user=self.peer1_user, employee_id='P001')
        self.peer2 = _make_employee(self.company, user=self.peer2_user, employee_id='P002')
        for emp in (self.creator_emp, self.peer1, self.peer2):
            _enable_chat(self.company, emp)

    def test_create_group_conversation(self):
        conv = create_group_conversation(
            self.creator,
            'Team Chat',
            [self.peer1_user, self.peer2_user],
            self.company,
        )
        self.assertEqual(conv.conversation_type, TYPE_GROUP)
        self.assertEqual(conv.title, 'Team Chat')
        self.assertEqual(conv.participants.count(), 3)

    def test_validate_group_rejects_out_of_scope(self):
        outsider = _make_user('outsider')
        _make_employee(self.company, user=outsider, employee_id='OUT01')
        with self.assertRaises(ValidationError):
            create_group_conversation(
                self.creator,
                'Bad Group',
                [self.peer1_user, outsider],
                self.company,
            )

    def test_create_group_with_avatar(self):
        avatar = SimpleUploadedFile('team.png', b'fake-image-bytes', content_type='image/png')
        conv = create_group_conversation(
            self.creator,
            'Team Chat',
            [self.peer1_user, self.peer2_user],
            self.company,
            group_avatar=avatar,
        )
        conv.refresh_from_db()
        self.assertTrue(conv.group_avatar.name)
        self.assertIn('group_avatars/', conv.group_avatar.name)

    def test_create_group_without_avatar_uses_initial(self):
        conv = create_group_conversation(
            self.creator,
            'Team Chat',
            [self.peer1_user, self.peer2_user],
            self.company,
        )
        self.assertFalse(conv.group_avatar)
        self.assertEqual(conv.get_group_avatar_initial(), 'T')

    def test_group_avatar_initial_fallback_g(self):
        conv = Conversation(
            company=self.company,
            conversation_type=TYPE_GROUP,
            title='',
            created_by=self.creator,
        )
        self.assertEqual(conv.get_group_avatar_initial(), 'G')


class InboxTests(TestCase):
    def setUp(self):
        self.company = _make_company('Acme')
        self.admin = _make_chat_admin('admin', self.company)
        self.emp_user = _make_user('emp')
        self.employee = _make_employee(self.company, user=self.emp_user)
        _enable_chat(self.company, self.employee)
        self.conv, _ = get_or_create_admin_support_conversation(self.admin, self.employee)
        send_message(self.conv, self.admin, 'Hello')

    def test_inbox_lists_participant_conversations(self):
        qs = inbox_for_user(self.emp_user)
        self.assertIn(self.conv, qs)

    def test_inbox_excludes_non_participant(self):
        outsider = _make_user('outsider')
        qs = inbox_for_user(outsider)
        self.assertNotIn(self.conv, qs)


class ArchiveConversationTests(TestCase):
    def setUp(self):
        self.company = _make_company('Acme')
        self.admin = _make_chat_admin('admin', self.company)
        self.emp_user = _make_user('emp')
        self.employee = _make_employee(self.company, user=self.emp_user)
        _enable_chat(self.company, self.employee)
        self.conv, _ = get_or_create_admin_support_conversation(self.admin, self.employee)

    def test_archive_conversation(self):
        archive_conversation(self.conv, self.admin)
        self.conv.refresh_from_db()
        self.assertTrue(self.conv.is_archived)
        self.assertIsNotNone(self.conv.archived_at)
        self.assertEqual(self.conv.archived_by, self.admin)
