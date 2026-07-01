import datetime

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from unittest.mock import patch

from accounts.models import UserCompanyAccess, UserProfile
from companies.models import Company
from employees.models import Employee
from messaging.attachment_validation import ATTACHMENT_TYPE_GIF, ATTACHMENT_TYPE_IMAGE
from messaging.models import MessageAttachment
from messaging.services import (
    get_or_create_admin_support_conversation,
    message_preview_text,
    send_message,
    serialize_message_for_user,
)


def _make_company(name='Acme'):
    return Company.objects.create(name=name, email=f'{name.lower()}@test.local')


def _make_user(username, password='testpass123'):
    return User.objects.create_user(username=username, password=password)


def _make_employee(company, user=None, **kwargs):
    defaults = {
        'company': company,
        'employee_id': 'E001',
        'first_name': 'Ana',
        'last_name': 'Reyes',
        'email': 'ana@test.local',
        'date_hired': datetime.date(2024, 1, 1),
        'status': 'active',
        'can_use_chat': True,
    }
    defaults.update(kwargs)
    employee = Employee.objects.create(**defaults)
    company.employee_chat_enabled = True
    company.save(update_fields=['employee_chat_enabled'])
    if user:
        employee.user = user
        employee.save(update_fields=['user'])
    return employee


def _make_chat_admin(username, company):
    user = _make_user(username)
    UserProfile.objects.create(user=user, can_manage_chat=True)
    UserCompanyAccess.objects.create(user=user, company=company, role='hr_admin', is_active=True)
    return user


def _image_file(name='photo.jpg', content=b'jpeg-bytes', content_type='image/jpeg'):
    return SimpleUploadedFile(name, content, content_type=content_type)


def _gif_file(name='anim.gif', content=b'gif-bytes'):
    return SimpleUploadedFile(name, content, content_type='image/gif')


class SendMessageAttachmentTests(TestCase):
    def setUp(self):
        self.company = _make_company()
        self.admin = _make_chat_admin('admin', self.company)
        self.emp_user = _make_user('emp')
        UserProfile.objects.create(user=self.emp_user, role='employee')
        self.employee = _make_employee(self.company, user=self.emp_user)
        self.conv, _ = get_or_create_admin_support_conversation(self.admin, self.employee)

    def test_send_text_and_image_attachment(self):
        msg = send_message(
            self.conv,
            self.admin,
            'See attached',
            attachment=_image_file(),
        )
        self.assertEqual(msg.body, 'See attached')
        self.assertEqual(msg.attachments.count(), 1)
        att = msg.attachments.get()
        self.assertEqual(att.attachment_type, ATTACHMENT_TYPE_IMAGE)
        self.assertEqual(att.uploaded_by, self.admin)

    def test_send_image_only_message(self):
        msg = send_message(self.conv, self.admin, '', attachment=_image_file())
        self.assertEqual(msg.body, '')
        self.assertEqual(msg.attachments.count(), 1)

    def test_send_gif_attachment(self):
        msg = send_message(self.conv, self.admin, '', attachment=_gif_file())
        att = msg.attachments.get()
        self.assertEqual(att.attachment_type, ATTACHMENT_TYPE_GIF)

    def test_empty_message_without_attachment_rejected(self):
        with self.assertRaises(ValidationError):
            send_message(self.conv, self.admin, '')

    def test_unsupported_file_rejected(self):
        bad = SimpleUploadedFile('doc.pdf', b'pdf', content_type='application/pdf')
        with self.assertRaises(ValidationError):
            send_message(self.conv, self.admin, '', attachment=bad)

    def test_file_over_10mb_rejected(self):
        huge = SimpleUploadedFile('big.jpg', b'x' * (10 * 1024 * 1024 + 1), content_type='image/jpeg')
        with self.assertRaises(ValidationError):
            send_message(self.conv, self.admin, '', attachment=huge)

    def test_message_preview_text_for_image_only(self):
        msg = send_message(self.conv, self.admin, '', attachment=_image_file())
        self.assertEqual(message_preview_text(msg, self.admin), 'Photo')

    def test_message_preview_text_for_gif_only(self):
        msg = send_message(self.conv, self.admin, '', attachment=_gif_file())
        self.assertEqual(message_preview_text(msg, self.admin), 'GIF')


class AttachmentAccessTests(TestCase):
    def setUp(self):
        self.company = _make_company()
        self.admin = _make_chat_admin('admin', self.company)
        self.emp_user = _make_user('emp')
        UserProfile.objects.create(user=self.emp_user, role='employee')
        self.employee = _make_employee(self.company, user=self.emp_user)
        self.conv, _ = get_or_create_admin_support_conversation(self.admin, self.employee)
        self.msg = send_message(self.conv, self.admin, 'Pic', attachment=_image_file())
        self.attachment = self.msg.attachments.get()

        self.outsider = _make_user('outsider')
        UserProfile.objects.create(user=self.outsider, role='employee')

    def test_participant_can_access_attachment(self):
        self.client.login(username='emp', password='testpass123')
        response = self.client.get(reverse('messaging:attachment_view', args=[self.attachment.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/jpeg')

    def test_non_participant_denied(self):
        self.client.login(username='outsider', password='testpass123')
        with self.assertRaises(PermissionDenied):
            self.client.get(reverse('messaging:attachment_view', args=[self.attachment.pk]))

    def test_admin_support_attachment_masks_sender_for_employee(self):
        data = serialize_message_for_user(self.msg, self.emp_user)
        self.assertEqual(data['sender_display'], 'HR Support')
        self.assertEqual(len(data['attachments']), 1)
        self.assertIn('/messaging/attachments/', data['attachments'][0]['url'])


class AttachmentViewHttpTests(TestCase):
    def setUp(self):
        self.company = _make_company()
        self.admin = _make_chat_admin('admin', self.company)
        self.emp_user = _make_user('emp')
        UserProfile.objects.create(user=self.emp_user, role='employee')
        self.employee = _make_employee(self.company, user=self.emp_user)
        self.conv, _ = get_or_create_admin_support_conversation(self.admin, self.employee)

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_admin_thread_post_text_and_attachment(self, _mock):
        self.client.login(username='admin', password='testpass123')
        response = self.client.post(reverse('messaging:thread', args=[self.conv.pk]), {
            'body': 'Check this out',
            'attachment': _image_file(),
        })
        self.assertEqual(response.status_code, 302)
        msg = self.conv.messages.latest('created_at')
        self.assertEqual(msg.body, 'Check this out')
        self.assertEqual(msg.attachments.count(), 1)

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_portal_thread_post_image_only(self, _mock):
        self.client.login(username='emp', password='testpass123')
        response = self.client.post(reverse('portal:messages_thread', args=[self.conv.pk]), {
            'body': '',
            'attachment': _image_file('portal.jpg'),
        })
        self.assertEqual(response.status_code, 302)
        msg = self.conv.messages.filter(sender_user=self.emp_user).latest('created_at')
        self.assertEqual(msg.body, '')
        self.assertEqual(msg.attachments.count(), 1)

    def test_thread_page_renders_attachment_ui(self):
        self.client.login(username='admin', password='testpass123')
        response = self.client.get(reverse('messaging:thread', args=[self.conv.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'msgChatAttachmentInput')
        self.assertContains(response, 'msgChatAttachBtn')
        self.assertContains(response, 'enctype="multipart/form-data"')


class AttachmentPollingApiTests(TestCase):
    def setUp(self):
        self.company = _make_company()
        self.admin = _make_chat_admin('admin', self.company)
        self.emp_user = _make_user('emp')
        UserProfile.objects.create(user=self.emp_user, role='employee')
        self.employee = _make_employee(self.company, user=self.emp_user)
        self.conv, _ = get_or_create_admin_support_conversation(self.admin, self.employee)

    def test_thread_api_includes_attachment_metadata(self):
        send_message(self.conv, self.admin, 'Image', attachment=_image_file())
        self.client.login(username='emp', password='testpass123')
        response = self.client.get(reverse('portal:messages_thread_api', args=[self.conv.pk]))
        self.assertEqual(response.status_code, 200)
        message = response.json()['messages'][0]
        self.assertEqual(message['body'], 'Image')
        self.assertEqual(len(message['attachments']), 1)
        self.assertEqual(message['attachments'][0]['attachment_type'], ATTACHMENT_TYPE_IMAGE)
        self.assertIn('url', message['attachments'][0])

    def test_thread_api_after_id_returns_new_attachment_message(self):
        first = send_message(self.conv, self.admin, 'First')
        send_message(self.conv, self.admin, '', attachment=_gif_file())
        self.client.login(username='emp', password='testpass123')
        response = self.client.get(
            reverse('portal:messages_thread_api', args=[self.conv.pk]),
            {'after_id': first.pk},
        )
        self.assertEqual(response.status_code, 200)
        messages = response.json()['messages']
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]['attachments'][0]['attachment_type'], ATTACHMENT_TYPE_GIF)

    def test_employee_sees_support_persona_on_attachment_message(self):
        send_message(self.conv, self.admin, '', attachment=_image_file())
        self.client.login(username='emp', password='testpass123')
        response = self.client.get(reverse('portal:messages_thread_api', args=[self.conv.pk]))
        message = response.json()['messages'][0]
        self.assertEqual(message['sender_display'], 'HR Support')
        self.assertEqual(message['sender_avatar']['variant'], 'support')
