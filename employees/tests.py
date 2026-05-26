from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


class EmployeeAccessTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(
            username='admin_test', password='testpass123'
        )
        self.regular_user = User.objects.create_user(
            username='employee_test', password='testpass123'
        )

    def test_employee_list_requires_login(self):
        response = self.client.get(reverse('employees:employee_list'))
        self.assertIn(response.status_code, [302, 403])
        if response.status_code == 302:
            self.assertIn('/accounts/login/', response['Location'])

    def test_regular_user_without_permission_gets_403(self):
        self.client.login(username='employee_test', password='testpass123')
        response = self.client.get(reverse('employees:employee_list'))
        self.assertEqual(response.status_code, 403)

    def test_superuser_can_access_employee_list(self):
        self.client.login(username='admin_test', password='testpass123')
        response = self.client.get(reverse('employees:employee_list'))
        self.assertEqual(response.status_code, 200)
