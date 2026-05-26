from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


class LicenseAccessTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(
            username='admin_test', password='testpass123'
        )
        self.regular_user = User.objects.create_user(
            username='employee_test', password='testpass123'
        )

    def test_license_status_requires_login(self):
        response = self.client.get(reverse('licenses:license_status'))
        self.assertIn(response.status_code, [302, 403])
        if response.status_code == 302:
            self.assertIn('/accounts/login/', response['Location'])

    def test_license_activate_requires_login(self):
        response = self.client.get(reverse('licenses:activate_license'))
        self.assertIn(response.status_code, [302, 403])
        if response.status_code == 302:
            self.assertIn('/accounts/login/', response['Location'])

    def test_regular_user_cannot_access_license_status(self):
        self.client.login(username='employee_test', password='testpass123')
        response = self.client.get(reverse('licenses:license_status'))
        self.assertEqual(response.status_code, 403)

    def test_regular_user_cannot_access_license_activate(self):
        self.client.login(username='employee_test', password='testpass123')
        response = self.client.get(reverse('licenses:activate_license'))
        self.assertEqual(response.status_code, 403)

    def test_superuser_can_access_license_status(self):
        self.client.login(username='admin_test', password='testpass123')
        response = self.client.get(reverse('licenses:license_status'))
        self.assertEqual(response.status_code, 200)

    def test_superuser_can_access_license_activate(self):
        self.client.login(username='admin_test', password='testpass123')
        response = self.client.get(reverse('licenses:activate_license'))
        self.assertEqual(response.status_code, 200)
