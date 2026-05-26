from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


class DashboardAccessTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(
            username='admin_test', password='testpass123'
        )

    def test_dashboard_requires_login(self):
        response = self.client.get(reverse('dashboard_home'))
        self.assertIn(response.status_code, [302, 403])
        if response.status_code == 302:
            self.assertIn('/accounts/login/', response['Location'])

    def test_superuser_can_access_dashboard(self):
        self.client.login(username='admin_test', password='testpass123')
        response = self.client.get(reverse('dashboard_home'))
        self.assertEqual(response.status_code, 200)
