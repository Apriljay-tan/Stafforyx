import datetime
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.avatars import (
    avatar_for_employee,
    avatar_for_user_as_viewer,
    avatar_for_user_profile,
    initials_for_employee,
    initials_for_support,
    initials_for_user,
    photo_url_for_employee,
    resolve_message_sender_avatar,
)
from accounts.models import UserCompanyAccess, UserProfile
from companies.models import Company
from employees.models import Employee
from messaging.services import get_or_create_admin_support_conversation, send_message


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


class AvatarHelperTests(TestCase):
    def test_employee_initials_from_name(self):
        employee = _make_employee(_make_company(), first_name='Ana', last_name='Reyes')
        self.assertEqual(initials_for_employee(employee), 'AR')

    def test_user_initials_from_name(self):
        user = _make_user('jdoe')
        user.first_name = 'John'
        user.last_name = 'Doe'
        user.save(update_fields=['first_name', 'last_name'])
        self.assertEqual(initials_for_user(user), 'JD')

    def test_support_initials_from_display_name(self):
        company = _make_company()
        self.assertEqual(initials_for_support(company), 'HR')
        company.chat_support_display_name = 'Company Desk'
        company.save(update_fields=['chat_support_display_name'])
        self.assertEqual(initials_for_support(company), 'CD')

    @override_settings(MEDIA_ROOT='')
    def test_employee_avatar_returns_image_url_when_photo_set(self):
        employee = _make_employee(_make_company())
        employee.photo = SimpleUploadedFile('photo.png', b'bytes', content_type='image/png')
        employee.save(update_fields=['photo'])
        avatar = avatar_for_employee(employee)
        self.assertTrue(avatar['image_url'])
        self.assertEqual(avatar['initials'], 'AR')

    def test_user_profile_avatar_without_photo_uses_initials(self):
        user = _make_user('admin')
        user.first_name = 'Pat'
        user.last_name = 'Lee'
        user.save(update_fields=['first_name', 'last_name'])
        UserProfile.objects.create(user=user, role='hr_admin')
        avatar = avatar_for_user_profile(user)
        self.assertIsNone(avatar['image_url'])
        self.assertEqual(avatar['initials'], 'PL')

    def test_admin_support_hides_real_admin_photo_from_employee(self):
        company = _make_company()
        admin = _make_user('admin')
        UserProfile.objects.create(user=admin, role='hr_admin', can_manage_chat=True)
        UserCompanyAccess.objects.create(user=admin, company=company, role='hr_admin', is_active=True)
        admin.stafforyx_profile.profile_photo = SimpleUploadedFile('admin.png', b'bytes', content_type='image/png')
        admin.stafforyx_profile.save(update_fields=['profile_photo'])

        emp_user = _make_user('emp')
        UserProfile.objects.create(user=emp_user, role='employee')
        employee = _make_employee(company, user=emp_user)
        conv, _ = get_or_create_admin_support_conversation(admin, employee)
        msg = send_message(conv, admin, 'Hello')

        avatar = resolve_message_sender_avatar(msg, emp_user)
        self.assertIsNone(avatar['image_url'])
        self.assertEqual(avatar['variant'], 'support')
        self.assertNotEqual(avatar['initials'], initials_for_user(admin))


class ProfilePhotoViewTests(TestCase):
    def setUp(self):
        self.company = _make_company()
        self.emp_user = _make_user('portal_emp')
        UserProfile.objects.create(user=self.emp_user, role='employee')
        self.employee = _make_employee(self.company, user=self.emp_user)

        self.admin = _make_user('hr_admin')
        UserProfile.objects.create(user=self.admin, role='hr_admin')
        UserCompanyAccess.objects.create(user=self.admin, company=self.company, role='hr_admin', is_active=True)

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_employee_can_update_own_photo(self, _mock_license):
        photo = SimpleUploadedFile('me.jpg', b'photo-bytes', content_type='image/jpeg')
        self.client.login(username='portal_emp', password='testpass123')
        response = self.client.post(reverse('portal:profile'), {'photo': photo})
        self.assertEqual(response.status_code, 302)
        self.employee.refresh_from_db()
        self.assertTrue(self.employee.photo.name)
        self.assertTrue(photo_url_for_employee(self.employee))

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_employee_cannot_update_another_employee_photo(self, _mock_license):
        other_user = _make_user('other')
        UserProfile.objects.create(user=other_user, role='employee')
        other = _make_employee(self.company, user=other_user, employee_id='E002')
        self.client.login(username='portal_emp', password='testpass123')
        self.client.post(reverse('portal:profile'), {
            'photo': SimpleUploadedFile('hack.jpg', b'x', content_type='image/jpeg'),
        })
        other.refresh_from_db()
        self.assertFalse(other.photo)

    def test_admin_can_update_own_profile_photo(self):
        photo = SimpleUploadedFile('admin.jpg', b'admin-bytes', content_type='image/jpeg')
        self.client.login(username='hr_admin', password='testpass123')
        response = self.client.post(reverse('accounts:profile'), {'profile_photo': photo})
        self.assertEqual(response.status_code, 302)
        profile = UserProfile.objects.get(user=self.admin)
        self.assertTrue(profile.profile_photo.name)

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_invalid_image_type_rejected(self, _mock_license):
        bad = SimpleUploadedFile('bad.gif', b'gif', content_type='image/gif')
        self.client.login(username='portal_emp', password='testpass123')
        response = self.client.post(reverse('portal:profile'), {'photo': bad}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.employee.refresh_from_db()
        self.assertFalse(self.employee.photo)

    def test_employee_sees_support_avatar_not_admin_photo_in_message_api(self):
        admin = _make_user('chat_admin')
        profile = UserProfile.objects.create(user=admin, role='hr_admin', can_manage_chat=True)
        profile.profile_photo = SimpleUploadedFile('admin.png', b'bytes', content_type='image/png')
        profile.save(update_fields=['profile_photo'])
        UserCompanyAccess.objects.create(user=admin, company=self.company, role='hr_admin', is_active=True)
        conv, _ = get_or_create_admin_support_conversation(admin, self.employee)
        send_message(conv, admin, 'Hi')

        self.client.login(username='portal_emp', password='testpass123')
        response = self.client.get(reverse('portal:messages_thread_api', args=[conv.pk]))
        self.assertEqual(response.status_code, 200)
        message = response.json()['messages'][0]
        self.assertIsNone(message['sender_avatar']['image_url'])
        self.assertEqual(message['sender_avatar']['variant'], 'support')

    def test_portal_profile_renders_bounded_circular_avatar(self):
        self.employee.photo = SimpleUploadedFile('photo.png', b'bytes', content_type='image/png')
        self.employee.save(update_fields=['photo'])
        self.client.login(username='portal_emp', password='testpass123')
        response = self.client.get(reverse('portal:profile'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'staff-avatar--xl')
        self.assertContains(response, 'profile-photo-preview')
        self.assertContains(response, 'data-profile-photo-crop')
        self.assertContains(response, 'profile-photo-crop.js')
        self.assertContains(response, 'class="staff-avatar staff-avatar--xl"')

    def test_admin_profile_renders_bounded_circular_avatar(self):
        profile = UserProfile.objects.get(user=self.admin)
        profile.profile_photo = SimpleUploadedFile('admin.png', b'bytes', content_type='image/png')
        profile.save(update_fields=['profile_photo'])
        self.client.login(username='hr_admin', password='testpass123')
        response = self.client.get(reverse('accounts:profile'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'staff-avatar--xl')
        self.assertContains(response, 'profile-photo-preview')
        self.assertContains(response, 'cropper.min.js')

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_employee_clear_photo(self, _mock_license):
        self.employee.photo = SimpleUploadedFile('photo.png', b'bytes', content_type='image/png')
        self.employee.save(update_fields=['photo'])
        self.client.login(username='portal_emp', password='testpass123')
        response = self.client.post(reverse('portal:profile'), {'clear_photo': '1'})
        self.assertEqual(response.status_code, 302)
        self.employee.refresh_from_db()
        self.assertFalse(self.employee.photo)

    def test_admin_clear_profile_photo(self):
        profile = UserProfile.objects.get(user=self.admin)
        profile.profile_photo = SimpleUploadedFile('admin.png', b'bytes', content_type='image/png')
        profile.save(update_fields=['profile_photo'])
        self.client.login(username='hr_admin', password='testpass123')
        response = self.client.post(reverse('accounts:profile'), {'clear_photo': '1'})
        self.assertEqual(response.status_code, 302)
        profile.refresh_from_db()
        self.assertFalse(profile.profile_photo)
