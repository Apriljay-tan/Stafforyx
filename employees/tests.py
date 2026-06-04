import datetime
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from companies.models import Company
from .forms import EmployeeForm
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


class EmployeeAttendancePolicyPhase1Tests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(
            username='admin_policy', password='testpass123'
        )
        self.company = Company.objects.create(
            name='Policy Corp', email='policy@test.com'
        )

    def _employee_data(self, **overrides):
        data = {
            'company': str(self.company.pk),
            'employee_id': 'P001',
            'first_name': 'Polly',
            'middle_name': '',
            'last_name': 'Policy',
            'email': 'polly@test.com',
            'phone': '',
            'address': '',
            'date_hired': '2024-01-01',
            'department': '',
            'position': '',
            'employment_type': 'regular',
            'status': 'active',
            'pay_basis': 'daily',
            'basic_salary': '0.00',
            'daily_rate': '',
            'work_schedule': '',
            'overtime_policy': 'request_required',
            'biometric_user_id': '',
            'sss_number': '',
            'philhealth_number': '',
            'pagibig_number': '',
            'tin_number': '',
            'sss_contribution_amount': '0.00',
            'philhealth_contribution_amount': '0.00',
            'pagibig_contribution_amount': '0.00',
            'tax_deduction_amount': '0.00',
            'emergency_contact_name': '',
            'emergency_contact_phone': '',
            'attendance_policy_type': 'fixed',
            'required_daily_hours': '8.00',
            'default_break_minutes': '60',
            'flexible_overtime_grace_minutes': '30',
            'flexible_day_offs': [],
            'night_differential_percentage': '10.00',
            'night_differential_start_time': '22:00',
            'night_differential_end_time': '06:00',
        }
        data.update(overrides)
        return data

    def test_employee_defaults_to_fixed_attendance_policy(self):
        employee = Employee.objects.create(
            company=self.company,
            employee_id='P000',
            first_name='Default',
            last_name='Fixed',
            email='fixed@test.com',
            date_hired=datetime.date(2024, 1, 1),
        )

        self.assertEqual(employee.attendance_policy_type, 'fixed')
        self.assertEqual(employee.overtime_policy, 'no_ot')
        self.assertEqual(employee.required_daily_hours, Decimal('8.00'))
        self.assertEqual(employee.default_break_minutes, 60)
        self.assertEqual(employee.flexible_overtime_grace_minutes, 30)
        self.assertEqual(employee.flexible_day_offs, [])
        self.assertFalse(employee.night_differential_enabled)
        self.assertEqual(employee.night_differential_percentage, Decimal('10.00'))
        self.assertEqual(employee.night_differential_start_time, datetime.time(22, 0))
        self.assertEqual(employee.night_differential_end_time, datetime.time(6, 0))
        self.assertFalse(employee.allow_other_registered_locations)

    @mock.patch('licenses.middleware.is_license_active', return_value=True)
    def test_flexible_policy_can_be_created_and_edited(self, _is_license_active):
        self.client.login(username='admin_policy', password='testpass123')
        create_data = self._employee_data(
            employee_id='P002',
            attendance_policy_type='flexible',
            required_daily_hours='7.50',
            default_break_minutes='30',
            flexible_overtime_grace_minutes='45',
            overtime_policy='automatic',
            flexible_day_offs=['sat', 'sun'],
            night_differential_enabled='on',
            night_differential_percentage='12.50',
            allow_other_registered_locations='on',
        )

        response = self.client.post(reverse('employees:employee_add'), create_data)

        employee = Employee.objects.get(employee_id='P002')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(employee.attendance_policy_type, 'flexible')
        self.assertEqual(employee.required_daily_hours, Decimal('7.50'))
        self.assertEqual(employee.default_break_minutes, 30)
        self.assertEqual(employee.flexible_overtime_grace_minutes, 45)
        self.assertEqual(employee.overtime_policy, 'automatic')
        self.assertEqual(employee.flexible_day_offs, ['sat', 'sun'])
        self.assertTrue(employee.night_differential_enabled)
        self.assertEqual(employee.night_differential_percentage, Decimal('12.50'))
        self.assertTrue(employee.allow_other_registered_locations)

        edit_data = self._employee_data(
            employee_id='P002',
            first_name='Polly',
            last_name='Policy',
            email='polly.updated@test.com',
            attendance_policy_type='fixed',
            required_daily_hours='8.00',
            default_break_minutes='60',
            flexible_overtime_grace_minutes='30',
            overtime_policy='request_required',
            flexible_day_offs=['sun'],
            night_differential_percentage='10.00',
        )
        response = self.client.post(
            reverse('employees:employee_edit', kwargs={'pk': employee.pk}),
            edit_data,
        )

        employee.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(employee.attendance_policy_type, 'fixed')
        self.assertEqual(employee.email, 'polly.updated@test.com')
        self.assertEqual(employee.overtime_policy, 'request_required')
        self.assertEqual(employee.flexible_day_offs, ['sun'])
        self.assertFalse(employee.night_differential_enabled)
        self.assertFalse(employee.allow_other_registered_locations)

    def test_attendance_policy_fields_validate_positive_values(self):
        form = EmployeeForm(data=self._employee_data(
            required_daily_hours='0.00',
            default_break_minutes='-1',
            flexible_overtime_grace_minutes='-1',
            night_differential_percentage='-0.01',
        ))

        self.assertFalse(form.is_valid())
        self.assertIn('required_daily_hours', form.errors)
        self.assertIn('default_break_minutes', form.errors)
        self.assertIn('flexible_overtime_grace_minutes', form.errors)
        self.assertIn('night_differential_percentage', form.errors)

    def test_employee_policy_pages_render(self):
        employee = Employee.objects.create(
            company=self.company,
            employee_id='P003',
            first_name='Rina',
            last_name='Render',
            email='rina@test.com',
            date_hired=datetime.date(2024, 1, 1),
            attendance_policy_type='flexible',
            required_daily_hours=Decimal('8.00'),
            flexible_day_offs=['sat', 'sun'],
            night_differential_enabled=True,
        )
        self.client.login(username='admin_policy', password='testpass123')

        checks = [
            (reverse('employees:employee_add'), 'Attendance Policy'),
            (reverse('employees:employee_edit', kwargs={'pk': employee.pk}), 'Attendance Policy'),
            (reverse('employees:employee_detail', kwargs={'pk': employee.pk}), 'Overtime Mode'),
            (reverse('employees:employee_list'), 'Flexible'),
        ]
        for url, expected in checks:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, expected)
