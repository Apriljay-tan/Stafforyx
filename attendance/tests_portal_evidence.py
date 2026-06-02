import datetime
import io
import tempfile
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from accounts.models import UserCompanyAccess, UserProfile
from attendance.models import AttendanceLocation, AttendancePortalLog, AttendanceRecord, WorkSchedule
from attendance.portal_services import get_client_ip
from companies.models import Company
from employees.models import Employee
from payroll.models import PayrollPeriod, PayrollRecord


def _make_selfie_file(filename='selfie.jpg'):
    image_buffer = io.BytesIO()
    Image.new('RGB', (6, 6), color=(120, 30, 30)).save(image_buffer, format='JPEG')
    return SimpleUploadedFile(filename, image_buffer.getvalue(), content_type='image/jpeg')


def _make_employee(company, employee_id, first_name='Emp', last_name='User'):
    return Employee.objects.create(
        company=company,
        employee_id=employee_id,
        first_name=first_name,
        last_name=last_name,
        date_hired=datetime.date(2024, 1, 1),
        status='active',
    )


def _make_schedule(company, name='All Week'):
    return WorkSchedule.objects.create(
        company=company,
        name=name,
        start_time=datetime.time(8, 0),
        end_time=datetime.time(17, 0),
        work_monday=True,
        work_tuesday=True,
        work_wednesday=True,
        work_thursday=True,
        work_friday=True,
        work_saturday=True,
        work_sunday=True,
    )


class TrustedProxyIpResolutionTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @override_settings(TRUSTED_PROXY=True)
    def test_trusted_proxy_uses_first_x_forwarded_for_ip(self):
        request = self.factory.get(
            '/attendance/portal/',
            HTTP_X_FORWARDED_FOR='203.0.113.15, 10.0.0.1',
            REMOTE_ADDR='127.0.0.1',
        )
        self.assertEqual(get_client_ip(request), '203.0.113.15')

    @override_settings(TRUSTED_PROXY=True)
    def test_trusted_proxy_falls_back_to_x_real_ip(self):
        request = self.factory.get(
            '/attendance/portal/',
            HTTP_X_REAL_IP='198.51.100.77',
            REMOTE_ADDR='127.0.0.1',
        )
        self.assertEqual(get_client_ip(request), '198.51.100.77')

    @override_settings(TRUSTED_PROXY=True)
    def test_trusted_proxy_falls_back_to_remote_addr(self):
        request = self.factory.get('/attendance/portal/', REMOTE_ADDR='192.0.2.44')
        self.assertEqual(get_client_ip(request), '192.0.2.44')

    @override_settings(TRUSTED_PROXY=False)
    def test_untrusted_proxy_ignores_xff_and_uses_remote_addr(self):
        request = self.factory.get(
            '/attendance/portal/',
            HTTP_X_FORWARDED_FOR='203.0.113.15, 10.0.0.1',
            REMOTE_ADDR='127.0.0.1',
        )
        self.assertEqual(get_client_ip(request), '127.0.0.1')


class AttendancePortalEvidenceAccessTests(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.temp_dir.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(self.temp_dir.cleanup)

        self.company_a = Company.objects.create(name='Company A', email='a@test.com')
        self.company_b = Company.objects.create(name='Company B', email='b@test.com')

        self.location_a = AttendanceLocation.objects.create(
            company=self.company_a,
            name='HQ Network',
            ip_address='127.0.0.1',
        )

        self.emp_a = _make_employee(self.company_a, 'A001', 'Alice', 'Alpha')
        self.emp_b = _make_employee(self.company_b, 'B001', 'Bob', 'Beta')

        self.superuser = User.objects.create_superuser('su_selfie', password='pass')

        self.hr_a = User.objects.create_user('hr_a', password='pass')
        UserCompanyAccess.objects.create(user=self.hr_a, company=self.company_a, role='hr_admin', is_active=True)
        UserProfile.objects.create(
            user=self.hr_a,
            role='hr_admin',
            is_active_stafforyx=True,
            can_manage_attendance=True,
        )

        self.hr_b = User.objects.create_user('hr_b', password='pass')
        UserCompanyAccess.objects.create(user=self.hr_b, company=self.company_b, role='hr_admin', is_active=True)
        UserProfile.objects.create(
            user=self.hr_b,
            role='hr_admin',
            is_active_stafforyx=True,
            can_manage_attendance=True,
        )

        self.employee_user = User.objects.create_user('employee_plain', password='pass')
        UserProfile.objects.create(
            user=self.employee_user,
            role='employee',
            is_active_stafforyx=True,
            can_manage_attendance=False,
        )

        self.log_with_selfie = self._make_log(self.company_a, self.emp_a, with_selfie=True)
        self.log_without_selfie = self._make_log(self.company_a, self.emp_a, with_selfie=False)

    def _make_log(self, company, employee, *, with_selfie=True):
        log = AttendancePortalLog.objects.create(
            company=company,
            employee=employee,
            attendance_location=self.location_a if company == self.company_a else None,
            action='time_in',
            status='success',
            ip_address='127.0.0.1',
            gps_latitude='14.609100',
            gps_longitude='121.022300',
            gps_accuracy='12.50',
        )
        if with_selfie:
            log.selfie_image.save(f'selfie_{log.pk}.jpg', _make_selfie_file(), save=True)
        return log

    def test_authorized_hr_can_view_selfie_evidence(self):
        self.client.login(username='hr_a', password='pass')
        response = self.client.get(reverse('attendance:portal_log_selfie', args=[self.log_with_selfie.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get('Content-Type', '').startswith('image/'))
        response.close()

    def test_unauthorized_user_cannot_view_other_company_selfie(self):
        self.client.login(username='hr_b', password='pass')
        response = self.client.get(reverse('attendance:portal_log_selfie', args=[self.log_with_selfie.pk]))
        self.assertEqual(response.status_code, 404)

    def test_employee_cannot_view_other_employee_selfie(self):
        self.client.login(username='employee_plain', password='pass')
        response = self.client.get(reverse('attendance:portal_log_selfie', args=[self.log_with_selfie.pk]))
        # Employee-only users are confined to the portal by
        # EmployeePortalOnlyMiddleware: instead of a 403 they are redirected to
        # the Employee Portal. Either way they cannot view the selfie evidence.
        self.assertIn(response.status_code, [302, 403])

    def test_superuser_can_view_selfie_evidence(self):
        self.client.login(username='su_selfie', password='pass')
        response = self.client.get(reverse('attendance:portal_log_selfie', args=[self.log_with_selfie.pk]))
        self.assertEqual(response.status_code, 200)
        response.close()

    def test_selfie_view_returns_404_when_no_selfie_exists(self):
        self.client.login(username='hr_a', password='pass')
        response = self.client.get(reverse('attendance:portal_log_selfie', args=[self.log_without_selfie.pk]))
        self.assertEqual(response.status_code, 404)

    def test_portal_log_list_shows_selfie_indicator(self):
        self.client.login(username='hr_a', password='pass')
        response = self.client.get(reverse('attendance:portal_log_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Portal Evidence Logs')
        self.assertContains(response, 'Yes')
        self.assertContains(response, 'No')
        self.assertContains(response, reverse('attendance:portal_log_selfie', args=[self.log_with_selfie.pk]))

    def test_portal_log_detail_shows_selfie_status(self):
        self.client.login(username='hr_a', password='pass')
        detail_with = self.client.get(reverse('attendance:portal_log_detail', args=[self.log_with_selfie.pk]))
        self.assertEqual(detail_with.status_code, 200)
        self.assertContains(detail_with, 'View Selfie')

        detail_without = self.client.get(reverse('attendance:portal_log_detail', args=[self.log_without_selfie.pk]))
        self.assertEqual(detail_without.status_code, 200)
        self.assertContains(detail_without, 'No selfie captured for this log.')

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_manual_delete_selected_removes_log_and_selfie_file(self, _mock):
        selfie_name = self.log_with_selfie.selfie_image.name
        self.assertTrue(self.log_with_selfie.selfie_image.storage.exists(selfie_name))

        self.client.login(username='hr_a', password='pass')
        response = self.client.post(
            reverse('attendance:portal_log_list'),
            {
                'bulk_action': 'delete_selected',
                'selected_log_ids': [str(self.log_with_selfie.pk)],
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(AttendancePortalLog.objects.filter(pk=self.log_with_selfie.pk).exists())
        self.assertFalse(self.log_with_selfie.selfie_image.storage.exists(selfie_name))

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_unauthorized_user_cannot_wipe_logs(self, _mock):
        self.client.login(username='employee_plain', password='pass')
        response = self.client.post(
            reverse('attendance:portal_log_list'),
            {
                'bulk_action': 'delete_all_for_company',
                'target_company_id': str(self.company_a.pk),
            },
        )
        self.assertIn(response.status_code, [302, 403])
        self.assertTrue(AttendancePortalLog.objects.filter(pk=self.log_with_selfie.pk).exists())


class AttendancePortalLoggingToggleTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='Toggle Co', email='toggle@test.com')
        self.schedule = _make_schedule(self.company, name='Toggle Shift')
        self.employee = _make_employee(self.company, 'TGL001', 'Tina', 'Toggle')
        self.employee.work_schedule = self.schedule
        self.employee.save(update_fields=['work_schedule'])

        self.location = AttendanceLocation.objects.create(
            company=self.company,
            name='Office Network',
            ip_address='127.0.0.1',
        )
        self.user = User.objects.create_user('toggle_user', password='pass')
        self.employee.user = self.user
        self.employee.save(update_fields=['user'])
        self.portal_url = reverse('attendance:attendance_portal')

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_page_opened_logs_not_created_when_disabled(self, _mock):
        self.company.attendance_log_page_opened_events = False
        self.company.save(update_fields=['attendance_log_page_opened_events'])

        self.client.login(username='toggle_user', password='pass')
        response = self.client.get(self.portal_url)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            AttendancePortalLog.objects.filter(employee=self.employee, action='page_open').exists()
        )

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_time_in_logs_created_when_clock_actions_enabled(self, _mock):
        self.company.attendance_log_clock_actions = True
        self.company.save(update_fields=['attendance_log_clock_actions'])

        self.client.login(username='toggle_user', password='pass')
        response = self.client.post(self.portal_url, {'action': 'time_in'}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            AttendancePortalLog.objects.filter(employee=self.employee, action='time_in').exists()
        )

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_time_out_logs_created_when_clock_actions_enabled(self, _mock):
        self.company.attendance_log_clock_actions = True
        self.company.save(update_fields=['attendance_log_clock_actions'])

        self.client.login(username='toggle_user', password='pass')
        self.client.post(self.portal_url, {'action': 'time_in'}, follow=True)
        response = self.client.post(self.portal_url, {'action': 'time_out'}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            AttendancePortalLog.objects.filter(employee=self.employee, action='time_out').exists()
        )

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_blocked_attempt_logs_created_when_enabled(self, _mock):
        self.location.require_selfie = True
        self.location.save(update_fields=['require_selfie'])
        self.company.attendance_log_blocked_attempts = True
        self.company.save(update_fields=['attendance_log_blocked_attempts'])

        self.client.login(username='toggle_user', password='pass')
        response = self.client.post(self.portal_url, {'action': 'time_in'}, follow=True)
        self.assertEqual(response.status_code, 200)
        blocked_log = AttendancePortalLog.objects.filter(employee=self.employee, status='blocked').first()
        self.assertIsNotNone(blocked_log)
        self.assertIn('selfie', blocked_log.blocked_reason.lower())


class CleanupAttendanceSelfiesCommandTests(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.temp_dir.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(self.temp_dir.cleanup)

        self.company_a = Company.objects.create(
            name='Cleanup A',
            email='cleanup-a@test.com',
            attendance_selfie_retention_days=30,
        )
        self.company_b = Company.objects.create(
            name='Cleanup B',
            email='cleanup-b@test.com',
            attendance_selfie_retention_days=60,
        )

        self.emp_a = _make_employee(self.company_a, 'CA001', 'Clean', 'Alpha')
        self.emp_b = _make_employee(self.company_b, 'CB001', 'Clean', 'Beta')

    def _make_log(self, company, employee, age_days):
        log = AttendancePortalLog.objects.create(
            company=company,
            employee=employee,
            action='time_in',
            status='success',
            ip_address='127.0.0.1',
        )
        log.selfie_image.save(f'cleanup_{log.pk}.jpg', _make_selfie_file(filename=f'cleanup_{log.pk}.jpg'), save=True)
        old_time = timezone.now() - datetime.timedelta(days=age_days)
        AttendancePortalLog.objects.filter(pk=log.pk).update(created_at=old_time)
        log.refresh_from_db()
        return log

    def test_cleanup_command_dry_run_does_not_delete_files_or_clear_field(self):
        log = self._make_log(self.company_a, self.emp_a, age_days=40)
        self.assertTrue(log.selfie_image.storage.exists(log.selfie_image.name))

        with patch('sys.stdout', new=io.StringIO()):
            call_command('cleanup_attendance_selfies', '--dry-run')

        log.refresh_from_db()
        self.assertTrue(bool(log.selfie_image))
        self.assertTrue(log.selfie_image.storage.exists(log.selfie_image.name))

    def test_cleanup_command_deletes_old_selfie_and_clears_field(self):
        log = self._make_log(self.company_a, self.emp_a, age_days=40)
        selfie_name = log.selfie_image.name

        call_command('cleanup_attendance_selfies')

        log.refresh_from_db()
        self.assertFalse(bool(log.selfie_image))
        self.assertFalse(log.selfie_image.storage.exists(selfie_name))

    def test_cleanup_command_does_not_delete_recent_selfie(self):
        log = self._make_log(self.company_a, self.emp_a, age_days=5)

        call_command('cleanup_attendance_selfies')

        log.refresh_from_db()
        self.assertTrue(bool(log.selfie_image))
        self.assertTrue(log.selfie_image.storage.exists(log.selfie_image.name))

    def test_cleanup_respects_company_retention_days(self):
        # 10 days old: should be deleted for company A (retention 7), kept for company B (retention 60)
        self.company_a.attendance_selfie_retention_days = 7
        self.company_a.save(update_fields=['attendance_selfie_retention_days'])

        log_a = self._make_log(self.company_a, self.emp_a, age_days=10)
        log_b = self._make_log(self.company_b, self.emp_b, age_days=10)

        call_command('cleanup_attendance_selfies')

        log_a.refresh_from_db()
        log_b.refresh_from_db()
        self.assertFalse(bool(log_a.selfie_image))
        self.assertTrue(bool(log_b.selfie_image))

    def test_cleanup_days_override_works(self):
        # Company retention is 60, but override 7 should delete this 10-day-old selfie.
        log = self._make_log(self.company_b, self.emp_b, age_days=10)

        call_command('cleanup_attendance_selfies', '--days', '7')

        log.refresh_from_db()
        self.assertFalse(bool(log.selfie_image))

    def test_cleanup_company_id_filter_limits_scope(self):
        log_a = self._make_log(self.company_a, self.emp_a, age_days=40)
        log_b = self._make_log(self.company_b, self.emp_b, age_days=40)

        call_command('cleanup_attendance_selfies', '--company-id', str(self.company_a.pk))

        log_a.refresh_from_db()
        log_b.refresh_from_db()
        self.assertFalse(bool(log_a.selfie_image))
        self.assertTrue(bool(log_b.selfie_image))


class CleanupAttendancePortalLogsCommandTests(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.temp_dir.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(self.temp_dir.cleanup)

        self.company_a = Company.objects.create(
            name='Portal Cleanup A',
            email='portal-a@test.com',
            attendance_portal_log_retention_days=7,
            attendance_auto_delete_portal_logs=True,
        )
        self.company_b = Company.objects.create(
            name='Portal Cleanup B',
            email='portal-b@test.com',
            attendance_portal_log_retention_days=60,
            attendance_auto_delete_portal_logs=True,
        )

        self.emp_a = _make_employee(self.company_a, 'PCA001', 'Portal', 'Alpha')
        self.emp_b = _make_employee(self.company_b, 'PCB001', 'Portal', 'Beta')

    def _make_log(self, company, employee, age_days, action='time_in'):
        log = AttendancePortalLog.objects.create(
            company=company,
            employee=employee,
            action=action,
            status='success',
            ip_address='127.0.0.1',
        )
        log.selfie_image.save(f'portal_cleanup_{log.pk}.jpg', _make_selfie_file(), save=True)
        old_time = timezone.now() - datetime.timedelta(days=age_days)
        AttendancePortalLog.objects.filter(pk=log.pk).update(created_at=old_time)
        log.refresh_from_db()
        return log

    def test_dry_run_deletes_nothing(self):
        log = self._make_log(self.company_a, self.emp_a, age_days=30)
        selfie_name = log.selfie_image.name

        call_command('cleanup_attendance_portal_logs', '--dry-run')

        self.assertTrue(AttendancePortalLog.objects.filter(pk=log.pk).exists())
        self.assertTrue(log.selfie_image.storage.exists(selfie_name))

    def test_cleanup_deletes_only_matching_old_logs(self):
        old_log = self._make_log(self.company_a, self.emp_a, age_days=30, action='time_in')
        recent_log = self._make_log(self.company_a, self.emp_a, age_days=2, action='time_in')
        old_selfie_name = old_log.selfie_image.name

        call_command('cleanup_attendance_portal_logs')

        self.assertFalse(AttendancePortalLog.objects.filter(pk=old_log.pk).exists())
        self.assertFalse(old_log.selfie_image.storage.exists(old_selfie_name))
        self.assertTrue(AttendancePortalLog.objects.filter(pk=recent_log.pk).exists())

    def test_cleanup_respects_company_scope(self):
        log_a = self._make_log(self.company_a, self.emp_a, age_days=30)
        log_b = self._make_log(self.company_b, self.emp_b, age_days=30)

        call_command('cleanup_attendance_portal_logs', '--company-id', str(self.company_a.pk), '--days', '1')

        self.assertFalse(AttendancePortalLog.objects.filter(pk=log_a.pk).exists())
        self.assertTrue(AttendancePortalLog.objects.filter(pk=log_b.pk).exists())

    def test_cleanup_does_not_delete_attendance_or_payroll_records(self):
        attendance_record = AttendanceRecord.objects.create(
            company=self.company_a,
            employee=self.emp_a,
            date=datetime.date.today(),
            time_in=datetime.time(8, 0),
            status='present',
            source='portal',
        )
        period = PayrollPeriod.objects.create(
            company=self.company_a,
            name='May 2026',
            start_date=datetime.date(2026, 5, 1),
            end_date=datetime.date(2026, 5, 15),
            pay_date=datetime.date(2026, 5, 20),
        )
        payroll_record = PayrollRecord.objects.create(
            company=self.company_a,
            payroll_period=period,
            employee=self.emp_a,
        )

        log = self._make_log(self.company_a, self.emp_a, age_days=30)
        log.attendance_record = attendance_record
        log.save(update_fields=['attendance_record'])

        call_command('cleanup_attendance_portal_logs', '--days', '1')

        self.assertFalse(AttendancePortalLog.objects.filter(pk=log.pk).exists())
        self.assertTrue(AttendanceRecord.objects.filter(pk=attendance_record.pk).exists())
        self.assertTrue(PayrollRecord.objects.filter(pk=payroll_record.pk).exists())

    def test_cleanup_action_filter_and_page_open_only_option(self):
        old_page_open = self._make_log(self.company_a, self.emp_a, age_days=30, action='page_open')
        old_time_in = self._make_log(self.company_a, self.emp_a, age_days=30, action='time_in')

        call_command('cleanup_attendance_portal_logs', '--days', '1', '--delete-page-opened-only')

        self.assertFalse(AttendancePortalLog.objects.filter(pk=old_page_open.pk).exists())
        self.assertTrue(AttendancePortalLog.objects.filter(pk=old_time_in.pk).exists())
