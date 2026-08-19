import datetime

from django.contrib.auth.models import User
from django.test import TestCase

from accounts.models import UserProfile
from companies.models import Company
from employees.models import Employee


class ChatModelFieldTests(TestCase):
    def test_company_chat_defaults(self):
        company = Company.objects.create(name='Acme', email='a@acme.test')
        self.assertFalse(company.employee_chat_enabled)
        self.assertEqual(company.chat_support_display_name, '')

    def test_company_chat_fields_set(self):
        company = Company.objects.create(
            name='Acme',
            email='a@acme.test',
            employee_chat_enabled=True,
            chat_support_display_name='Company Desk',
        )
        self.assertTrue(company.employee_chat_enabled)
        self.assertEqual(company.chat_support_display_name, 'Company Desk')

    def test_employee_chat_defaults(self):
        company = Company.objects.create(name='Acme', email='a@acme.test')
        employee = Employee.objects.create(
            company=company,
            employee_id='E001',
            first_name='Ana',
            last_name='Reyes',
            email='ana@acme.test',
            date_hired=datetime.date(2024, 1, 1),
        )
        self.assertFalse(employee.can_use_chat)
        self.assertEqual(employee.allowed_chat_companies.count(), 0)

    def test_employee_allowed_chat_companies_m2m(self):
        company_a = Company.objects.create(name='Acme', email='a@acme.test')
        company_b = Company.objects.create(name='Beta', email='b@beta.test')
        employee = Employee.objects.create(
            company=company_a,
            employee_id='E001',
            first_name='Ana',
            last_name='Reyes',
            email='ana@acme.test',
            date_hired=datetime.date(2024, 1, 1),
            can_use_chat=True,
        )
        employee.allowed_chat_companies.add(company_b)
        self.assertEqual(employee.allowed_chat_companies.count(), 1)
        self.assertIn(company_b, employee.allowed_chat_companies.all())
        self.assertEqual(company_b.chat_enabled_employees.count(), 1)

    def test_user_profile_can_manage_chat_default(self):
        user = User.objects.create_user('hr1', password='x')
        profile = UserProfile.objects.create(user=user)
        self.assertFalse(profile.can_manage_chat)

    def test_user_profile_can_manage_chat_set(self):
        user = User.objects.create_user('hr2', password='x')
        profile = UserProfile.objects.create(user=user, can_manage_chat=True)
        self.assertTrue(profile.can_manage_chat)
