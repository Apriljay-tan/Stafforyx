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
from attendance.models import AttendanceLocation, AttendancePortalLog
from attendance.portal_services import get_client_ip
from companies.models import Company
from employees.models import Employee


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
        self.assertEqual(response.status_code, 403)

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
