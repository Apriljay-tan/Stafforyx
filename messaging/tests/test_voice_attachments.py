import datetime
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from accounts.models import UserCompanyAccess, UserProfile
from companies.models import Company
from employees.models import Employee
from messaging.attachment_validation import ATTACHMENT_TYPE_VOICE
from messaging.constants import ATTACHMENT_TYPE_IMAGE
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
    UserProfile.objects.create(user=user, can_manage_chat=True, role='hr_admin')
    UserCompanyAccess.objects.create(user=user, company=company, role='hr_admin', is_active=True)
    return user


def _voice_file(name='voice.webm', content=b'webm-audio', content_type='audio/webm'):
    return SimpleUploadedFile(name, content, content_type=content_type)


class VoiceAttachmentServiceTests(TestCase):
    def setUp(self):
        self.company = _make_company()
        self.admin = _make_chat_admin('chat_admin', self.company)
        self.emp_user = _make_user('emp')
        UserProfile.objects.create(user=self.emp_user, role='employee')
        self.employee = _make_employee(self.company, user=self.emp_user)
        self.conv, _ = get_or_create_admin_support_conversation(self.admin, self.employee)

    def test_admin_sends_voice_attachment(self):
        msg = send_message(self.conv, self.admin, '', attachment=_voice_file())
        att = msg.attachments.get()
        self.assertEqual(att.attachment_type, ATTACHMENT_TYPE_VOICE)
        self.assertEqual(att.uploaded_by, self.admin)

    def test_employee_sends_voice_attachment(self):
        msg = send_message(self.conv, self.emp_user, '', attachment=_voice_file('note.mp3', b'mp3', 'audio/mpeg'))
        att = msg.attachments.get()
        self.assertEqual(att.attachment_type, ATTACHMENT_TYPE_VOICE)
        self.assertEqual(att.uploaded_by, self.emp_user)

    def test_unsupported_audio_rejected(self):
        bad = SimpleUploadedFile('track.flac', b'flac', content_type='audio/flac')
        with self.assertRaises(ValidationError):
            send_message(self.conv, self.admin, '', attachment=bad)

    def test_voice_over_10mb_rejected(self):
        huge = SimpleUploadedFile('big.webm', b'x' * (10 * 1024 * 1024 + 1), content_type='audio/webm')
        with self.assertRaises(ValidationError):
            send_message(self.conv, self.admin, '', attachment=huge)

    def test_message_preview_text_for_voice_only(self):
        msg = send_message(self.conv, self.admin, '', attachment=_voice_file())
        self.assertEqual(message_preview_text(msg, self.admin), 'Voice message')

    def test_image_validation_unchanged(self):
        img = SimpleUploadedFile('x.jpg', b'jpg', content_type='image/jpeg')
        msg = send_message(self.conv, self.admin, '', attachment=img)
        self.assertEqual(msg.attachments.get().attachment_type, ATTACHMENT_TYPE_IMAGE)


class VoiceAttachmentHttpTests(TestCase):
    def setUp(self):
        self.company = _make_company()
        self.admin = _make_chat_admin('chat_admin', self.company)
        self.emp_user = _make_user('emp')
        UserProfile.objects.create(user=self.emp_user, role='employee')
        self.employee = _make_employee(self.company, user=self.emp_user)
        self.conv, _ = get_or_create_admin_support_conversation(self.admin, self.employee)
        self.msg = send_message(self.conv, self.admin, '', attachment=_voice_file())
        self.attachment = self.msg.attachments.get()
        self.outsider = _make_chat_admin('other_admin', _make_company('OtherCo'))

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_admin_thread_post_voice(self, _mock):
        self.client.login(username='chat_admin', password='testpass123')
        response = self.client.post(reverse('messaging:thread', args=[self.conv.pk]), {
            'body': '',
            'attachment': _voice_file('admin-voice.webm'),
        })
        self.assertEqual(response.status_code, 302)
        latest = self.conv.messages.latest('created_at')
        self.assertEqual(latest.attachments.get().attachment_type, ATTACHMENT_TYPE_VOICE)

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_portal_thread_post_voice(self, _mock):
        self.client.login(username='emp', password='testpass123')
        response = self.client.post(reverse('portal:messages_thread', args=[self.conv.pk]), {
            'body': '',
            'attachment': _voice_file('emp-voice.webm'),
        })
        self.assertEqual(response.status_code, 302)
        latest = self.conv.messages.filter(sender_user=self.emp_user).latest('created_at')
        self.assertEqual(latest.attachments.get().attachment_type, ATTACHMENT_TYPE_VOICE)

    def test_thread_page_renders_voice_ui(self):
        self.client.login(username='chat_admin', password='testpass123')
        response = self.client.get(reverse('messaging:thread', args=[self.conv.pk]))
        self.assertContains(response, 'msgChatVoiceBtn')
        self.assertContains(response, 'chat-composer.js')

    def test_participant_can_access_voice_attachment(self):
        self.client.login(username='emp', password='testpass123')
        response = self.client.get(reverse('messaging:attachment_view', args=[self.attachment.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response['Content-Type'].startswith('audio/'))

    def test_non_participant_denied_voice_attachment(self):
        self.client.login(username='other_admin', password='testpass123')
        response = self.client.get(reverse('messaging:attachment_view', args=[self.attachment.pk]))
        self.assertEqual(response.status_code, 403)

    def test_polling_api_includes_voice_metadata(self):
        self.client.login(username='emp', password='testpass123')
        response = self.client.get(reverse('portal:messages_thread_api', args=[self.conv.pk]))
        self.assertEqual(response.status_code, 200)
        message = response.json()['messages'][0]
        self.assertEqual(message['attachments'][0]['attachment_type'], ATTACHMENT_TYPE_VOICE)
        self.assertIn('url', message['attachments'][0])

    def test_admin_support_persona_masking_on_voice_message(self):
        data = serialize_message_for_user(self.msg, self.emp_user)
        self.assertEqual(data['sender_display'], 'HR Support')
        self.assertEqual(data['attachments'][0]['attachment_type'], ATTACHMENT_TYPE_VOICE)

        self.client.login(username='emp', password='testpass123')
        response = self.client.get(reverse('portal:messages_thread_api', args=[self.conv.pk]))
        message = response.json()['messages'][0]
        self.assertEqual(message['sender_display'], 'HR Support')
        self.assertEqual(message['sender_avatar']['variant'], 'support')
