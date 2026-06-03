import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from companies.models import Company
from .models import Employee


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


class EmployeeDailyRateDisplayTests(TestCase):
    """The employee list shows the Daily Rate column and per-employee rate."""

    def setUp(self):
        self.superuser = User.objects.create_superuser(
            username='admin_dr', password='testpass123'
        )
        self.company = Company.objects.create(name='DR Corp', email='dr@test.com')
        self.daily_emp = Employee.objects.create(
            company=self.company, employee_id='D001',
            first_name='Dana', last_name='Daily', email='dana@test.com',
            date_hired=datetime.date(2024, 1, 1),
            pay_basis='daily', daily_rate=Decimal('600.00'),
        )
        self.monthly_emp = Employee.objects.create(
            company=self.company, employee_id='M001',
            first_name='Monty', last_name='Monthly', email='monty@test.com',
            date_hired=datetime.date(2024, 1, 1),
            pay_basis='monthly', basic_salary=Decimal('26000.00'),
        )

    def test_list_renders_daily_rate_column(self):
        self.client.login(username='admin_dr', password='testpass123')
        response = self.client.get(reverse('employees:employee_list'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Column header present
        self.assertIn('Daily Rate', content)
        # Daily employee shows their explicit daily rate
        self.assertIn('600.00', content)

    def test_effective_daily_rate_property(self):
        self.assertEqual(self.daily_emp.effective_daily_rate, Decimal('600.00'))
        # Monthly computes basic_salary / 26 = 1000.00
        self.assertEqual(self.monthly_emp.effective_daily_rate, Decimal('1000.00'))
