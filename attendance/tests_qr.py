import base64
import datetime
import io
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from accounts.models import UserCompanyAccess
from attendance.models import (
    AttendanceKioskDevice,
    AttendanceLocation,
    AttendancePortalLog,
    AttendanceQRScanLog,
    AttendanceQRToken,
    AttendanceRecord,
    WorkSchedule,
)
from attendance.qr_services import create_qr_token, validate_qr_token_for_employee
from companies.models import Company
from employees.models import Employee
from payroll.models import PayrollPeriod, PayrollRecord


def _make_company(name='QR Co', **kwargs):
    defaults = {
        'name': name,
        'email': f'{name.lower().replace(" ", "-")}@example.com',
    }
    defaults.update(kwargs)
    return Company.objects.create(**defaults)


def _make_schedule(company):
    return WorkSchedule.objects.create(
        company=company,
        name='All Week',
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


_emp_counter = 0


def _make_employee(company, *, schedule=None, user=None, allow_other=False, flexible=False):
    global _emp_counter
    _emp_counter += 1
    employee = Employee.objects.create(
        company=company,
        user=user,
        employee_id=f'QR{_emp_counter:04d}',
        first_name='QR',
        last_name='Employee',
        date_hired=datetime.date(2024, 1, 1),
        status='active',
        work_schedule=schedule,
        allow_other_registered_locations=allow_other,
    )
    if flexible:
        employee.attendance_policy_type = Employee.ATTENDANCE_POLICY_FLEXIBLE
        employee.required_daily_hours = Decimal('8.00')
        employee.default_break_minutes = 0
        employee.flexible_overtime_grace_minutes = 30
        employee.flexible_day_offs = []
        employee.save(update_fields=[
            'attendance_policy_type',
            'required_daily_hours',
            'default_break_minutes',
            'flexible_overtime_grace_minutes',
            'flexible_day_offs',
        ])
    return employee


def _make_location(company, **kwargs):
    defaults = {
        'name': 'Branch',
        'ip_address': '127.0.0.1',
        'is_active': True,
    }
    defaults.update(kwargs)
    return AttendanceLocation.objects.create(company=company, **defaults)


def _make_kiosk(company, location, **kwargs):
    defaults = {
        'name': 'Store Tablet',
        'is_active': True,
    }
    defaults.update(kwargs)
    return AttendanceKioskDevice.objects.create(
        company=company,
        attendance_location=location,
        **defaults,
    )


def _selfie_payload():
    image_buffer = io.BytesIO()
    Image.new('RGB', (2, 2), color=(20, 80, 120)).save(image_buffer, format='JPEG')
    encoded = base64.b64encode(image_buffer.getvalue()).decode('ascii')
    return f'data:image/jpeg;base64,{encoded}'


class QRTokenServiceTests(TestCase):
    def setUp(self):
        self.company = _make_company(attendance_qr_validation_enabled=True)
        self.location = _make_location(self.company)
        self.kiosk = _make_kiosk(self.company, self.location)
        self.employee = _make_employee(self.company, schedule=_make_schedule(self.company))

    def test_valid_live_qr_token_allows_employee_and_logs_success(self):
        issued = create_qr_token(self.kiosk)

        result = validate_qr_token_for_employee(self.employee, issued.raw_token)

        self.assertTrue(result.allowed)
        self.assertEqual(result.result, 'success')
        self.assertEqual(result.attendance_location, self.location)
        self.assertEqual(result.kiosk_device, self.kiosk)
        self.assertFalse(
            AttendanceQRScanLog.objects.filter(token_hash=issued.raw_token).exists()
        )
        self.assertTrue(
            AttendanceQRScanLog.objects.filter(
                employee=self.employee,
                attendance_location=self.location,
                kiosk_device=self.kiosk,
                result='success',
                token_hash=issued.token.token_hash,
            ).exists()
        )

    def test_expired_qr_token_is_rejected(self):
        issued = create_qr_token(self.kiosk)
        issued.token.expires_at = issued.token.issued_at - datetime.timedelta(seconds=1)
        issued.token.save(update_fields=['expires_at'])

        result = validate_qr_token_for_employee(self.employee, issued.raw_token)

        self.assertFalse(result.allowed)
        self.assertEqual(result.result, 'expired')

    def test_inactive_kiosk_device_is_rejected(self):
        issued = create_qr_token(self.kiosk)
        self.kiosk.is_active = False
        self.kiosk.save(update_fields=['is_active'])

        result = validate_qr_token_for_employee(self.employee, issued.raw_token)

        self.assertFalse(result.allowed)
        self.assertEqual(result.result, 'inactive_device')

    def test_inactive_attendance_location_is_rejected(self):
        issued = create_qr_token(self.kiosk)
        self.location.is_active = False
        self.location.save(update_fields=['is_active'])

        result = validate_qr_token_for_employee(self.employee, issued.raw_token)

        self.assertFalse(result.allowed)
        self.assertEqual(result.result, 'inactive_location')

    def test_qr_from_unrelated_company_is_rejected(self):
        other_company = _make_company('Other QR Co', attendance_qr_validation_enabled=True)
        other_location = _make_location(other_company, ip_address='10.0.0.5')
        other_kiosk = _make_kiosk(other_company, other_location)
        issued = create_qr_token(other_kiosk)

        result = validate_qr_token_for_employee(self.employee, issued.raw_token)

        self.assertFalse(result.allowed)
        self.assertEqual(result.result, 'unauthorized')

    def test_employee_without_other_location_access_cannot_use_authorized_branch_qr(self):
        branch_company = _make_company('Branch QR Co', attendance_qr_validation_enabled=True)
        shared_admin = User.objects.create_user('shared_qr_admin', password='pass')
        UserCompanyAccess.objects.create(
            user=shared_admin, company=self.company, role='owner', is_active=True
        )
        UserCompanyAccess.objects.create(
            user=shared_admin, company=branch_company, role='owner', is_active=True
        )
        branch_location = _make_location(branch_company, ip_address='10.0.0.6')
        branch_kiosk = _make_kiosk(branch_company, branch_location)
        issued = create_qr_token(branch_kiosk)

        result = validate_qr_token_for_employee(self.employee, issued.raw_token)

        self.assertFalse(result.allowed)
        self.assertEqual(result.result, 'unauthorized')

    def test_employee_with_other_location_access_can_use_authorized_branch_qr(self):
        branch_company = _make_company('Branch QR Co', attendance_qr_validation_enabled=True)
        shared_admin = User.objects.create_user('shared_qr_admin_allowed', password='pass')
        UserCompanyAccess.objects.create(
            user=shared_admin, company=self.company, role='owner', is_active=True
        )
        UserCompanyAccess.objects.create(
            user=shared_admin, company=branch_company, role='owner', is_active=True
        )
        branch_location = _make_location(branch_company, ip_address='10.0.0.7')
        branch_kiosk = _make_kiosk(branch_company, branch_location)
        issued = create_qr_token(branch_kiosk)
        self.employee.allow_other_registered_locations = True
        self.employee.save(update_fields=['allow_other_registered_locations'])

        result = validate_qr_token_for_employee(self.employee, issued.raw_token)

        self.assertTrue(result.allowed)
        self.assertEqual(result.result, 'success')
        self.assertEqual(result.attendance_location, branch_location)

    def test_qr_token_lifetime_uses_company_setting(self):
        self.company.attendance_qr_token_lifetime_seconds = 120
        self.company.save(update_fields=['attendance_qr_token_lifetime_seconds'])
        issued_at = timezone.now()

        issued = create_qr_token(self.kiosk, now=issued_at)

        self.assertEqual(
            issued.token.expires_at,
            issued_at + datetime.timedelta(seconds=120),
        )

    def test_qr_token_lifetime_rejects_values_below_minimum(self):
        self.company.attendance_qr_token_lifetime_seconds = 29

        with self.assertRaises(ValidationError):
            self.company.full_clean()

    def test_qr_token_lifetime_rejects_values_above_maximum(self):
        self.company.attendance_qr_token_lifetime_seconds = 301

        with self.assertRaises(ValidationError):
            self.company.full_clean()

    def test_qr_generation_clamps_invalid_persisted_lifetime_values(self):
        Company.objects.filter(pk=self.company.pk).update(
            attendance_qr_token_lifetime_seconds=10
        )
        self.company.refresh_from_db()
        issued_at = timezone.now()

        issued = create_qr_token(self.kiosk, now=issued_at)

        self.assertEqual(
            issued.token.expires_at,
            issued_at + datetime.timedelta(seconds=30),
        )

    def test_qr_generation_marks_old_active_tokens_for_same_kiosk_inactive(self):
        first = create_qr_token(self.kiosk)

        second = create_qr_token(self.kiosk)

        first.token.refresh_from_db()
        self.assertFalse(first.token.is_active)
        self.assertTrue(second.token.is_active)

    def test_qr_generation_deletes_retained_expired_tokens_for_same_kiosk_when_enabled(self):
        self.company.attendance_qr_token_retention_days = 1
        self.company.attendance_auto_delete_qr_tokens = True
        self.company.save(update_fields=[
            'attendance_qr_token_retention_days',
            'attendance_auto_delete_qr_tokens',
        ])
        stale = _make_qr_token(
            self.kiosk,
            token_hash='stale-generation-token'.ljust(64, '0'),
            issued_at=timezone.now() - datetime.timedelta(days=3),
            expires_at=timezone.now() - datetime.timedelta(days=2),
        )

        create_qr_token(self.kiosk)

        self.assertFalse(AttendanceQRToken.objects.filter(pk=stale.pk).exists())

    def test_qr_generation_does_not_delete_scan_logs(self):
        self.company.attendance_qr_token_retention_days = 1
        self.company.attendance_auto_delete_qr_tokens = True
        self.company.save(update_fields=[
            'attendance_qr_token_retention_days',
            'attendance_auto_delete_qr_tokens',
        ])
        old_log = AttendanceQRScanLog.objects.create(
            employee=self.employee,
            company=self.company,
            attendance_location=self.location,
            kiosk_device=self.kiosk,
            action='validate',
            result='success',
        )
        AttendanceQRScanLog.objects.filter(pk=old_log.pk).update(
            created_at=timezone.now() - datetime.timedelta(days=30)
        )

        create_qr_token(self.kiosk)

        self.assertTrue(AttendanceQRScanLog.objects.filter(pk=old_log.pk).exists())


def _make_qr_token(kiosk, *, token_hash, issued_at, expires_at, is_active=True):
    return AttendanceQRToken.objects.create(
        kiosk_device=kiosk,
        attendance_location=kiosk.attendance_location,
        company=kiosk.company,
        token_hash=token_hash,
        issued_at=issued_at,
        expires_at=expires_at,
        is_active=is_active,
    )


def _make_scan_log(employee, kiosk, *, created_at, result='success'):
    log = AttendanceQRScanLog.objects.create(
        employee=employee,
        company=kiosk.company,
        attendance_location=kiosk.attendance_location,
        kiosk_device=kiosk,
        action='validate',
        result=result,
    )
    AttendanceQRScanLog.objects.filter(pk=log.pk).update(created_at=created_at)
    log.refresh_from_db()
    return log


class AttendanceQRDataCleanupCommandTests(TestCase):
    def setUp(self):
        self.company = _make_company(
            attendance_qr_validation_enabled=True,
            attendance_qr_token_retention_days=1,
            attendance_auto_delete_qr_tokens=True,
            attendance_qr_scan_log_retention_days=1,
            attendance_auto_delete_qr_scan_logs=False,
        )
        self.location = _make_location(self.company)
        self.kiosk = _make_kiosk(self.company, self.location)
        self.employee = _make_employee(self.company, schedule=_make_schedule(self.company))

    def call_cleanup(self, *args):
        output = io.StringIO()
        call_command('cleanup_attendance_qr_data', *args, stdout=output)
        return output.getvalue()

    def test_expired_tokens_older_than_retention_are_deleted(self):
        old_token = _make_qr_token(
            self.kiosk,
            token_hash='old-expired-token'.ljust(64, '0'),
            issued_at=timezone.now() - datetime.timedelta(days=3),
            expires_at=timezone.now() - datetime.timedelta(days=2),
        )

        output = self.call_cleanup()

        self.assertFalse(AttendanceQRToken.objects.filter(pk=old_token.pk).exists())
        self.assertIn('Companies scanned', output)
        self.assertIn('QR tokens deleted', output)
        self.assertIn('Dry run: no', output)

    def test_unexpired_tokens_are_not_deleted(self):
        live_token = _make_qr_token(
            self.kiosk,
            token_hash='live-token'.ljust(64, '0'),
            issued_at=timezone.now(),
            expires_at=timezone.now() + datetime.timedelta(seconds=60),
        )

        self.call_cleanup()

        self.assertTrue(AttendanceQRToken.objects.filter(pk=live_token.pk).exists())

    def test_dry_run_deletes_nothing(self):
        old_token = _make_qr_token(
            self.kiosk,
            token_hash='dry-run-token'.ljust(64, '0'),
            issued_at=timezone.now() - datetime.timedelta(days=3),
            expires_at=timezone.now() - datetime.timedelta(days=2),
        )

        output = self.call_cleanup('--dry-run')

        self.assertTrue(AttendanceQRToken.objects.filter(pk=old_token.pk).exists())
        self.assertIn('Dry run: yes', output)

    def test_scan_logs_are_not_deleted_when_company_auto_delete_is_false(self):
        old_log = _make_scan_log(
            self.employee,
            self.kiosk,
            created_at=timezone.now() - datetime.timedelta(days=2),
        )

        self.call_cleanup()

        self.assertTrue(AttendanceQRScanLog.objects.filter(pk=old_log.pk).exists())

    def test_scan_logs_are_deleted_when_company_auto_delete_is_true(self):
        self.company.attendance_auto_delete_qr_scan_logs = True
        self.company.save(update_fields=['attendance_auto_delete_qr_scan_logs'])
        old_log = _make_scan_log(
            self.employee,
            self.kiosk,
            created_at=timezone.now() - datetime.timedelta(days=2),
        )

        self.call_cleanup()

        self.assertFalse(AttendanceQRScanLog.objects.filter(pk=old_log.pk).exists())

    def test_cleanup_never_deletes_attendance_or_payroll_records(self):
        old_token = _make_qr_token(
            self.kiosk,
            token_hash='safe-token'.ljust(64, '0'),
            issued_at=timezone.now() - datetime.timedelta(days=3),
            expires_at=timezone.now() - datetime.timedelta(days=2),
        )
        old_log = _make_scan_log(
            self.employee,
            self.kiosk,
            created_at=timezone.now() - datetime.timedelta(days=2),
        )
        attendance_record = AttendanceRecord.objects.create(
            company=self.company,
            employee=self.employee,
            date=datetime.date.today(),
            status='present',
            source='portal',
        )
        period = PayrollPeriod.objects.create(
            company=self.company,
            name='QR Cleanup Period',
            start_date=datetime.date.today(),
            end_date=datetime.date.today(),
        )
        payroll_record = PayrollRecord.objects.create(
            company=self.company,
            payroll_period=period,
            employee=self.employee,
        )

        self.call_cleanup('--delete-old-scan-logs')

        self.assertFalse(AttendanceQRToken.objects.filter(pk=old_token.pk).exists())
        self.assertFalse(AttendanceQRScanLog.objects.filter(pk=old_log.pk).exists())
        self.assertTrue(AttendanceRecord.objects.filter(pk=attendance_record.pk).exists())
        self.assertTrue(PayrollRecord.objects.filter(pk=payroll_record.pk).exists())

    def test_company_filter_only_cleans_selected_company(self):
        other_company = _make_company(
            'Other Cleanup QR Co',
            attendance_qr_token_retention_days=1,
            attendance_auto_delete_qr_tokens=True,
        )
        other_location = _make_location(other_company, ip_address='10.20.30.40')
        other_kiosk = _make_kiosk(other_company, other_location)
        selected_token = _make_qr_token(
            self.kiosk,
            token_hash='selected-token'.ljust(64, '0'),
            issued_at=timezone.now() - datetime.timedelta(days=3),
            expires_at=timezone.now() - datetime.timedelta(days=2),
        )
        other_token = _make_qr_token(
            other_kiosk,
            token_hash='other-company-token'.ljust(64, '0'),
            issued_at=timezone.now() - datetime.timedelta(days=3),
            expires_at=timezone.now() - datetime.timedelta(days=2),
        )

        self.call_cleanup('--company-id', str(self.company.pk))

        self.assertFalse(AttendanceQRToken.objects.filter(pk=selected_token.pk).exists())
        self.assertTrue(AttendanceQRToken.objects.filter(pk=other_token.pk).exists())

    def test_days_override_is_used_for_tokens_and_scan_logs(self):
        self.company.attendance_auto_delete_qr_scan_logs = True
        self.company.save(update_fields=['attendance_auto_delete_qr_scan_logs'])
        recent_expired_token = _make_qr_token(
            self.kiosk,
            token_hash='recent-expired-token'.ljust(64, '0'),
            issued_at=timezone.now() - datetime.timedelta(days=2),
            expires_at=timezone.now() - datetime.timedelta(hours=12),
        )
        recent_log = _make_scan_log(
            self.employee,
            self.kiosk,
            created_at=timezone.now() - datetime.timedelta(hours=12),
        )

        self.call_cleanup('--days', '0')

        self.assertFalse(
            AttendanceQRToken.objects.filter(pk=recent_expired_token.pk).exists()
        )
        self.assertFalse(AttendanceQRScanLog.objects.filter(pk=recent_log.pk).exists())

    def test_qr_generation_still_works_after_cleanup(self):
        _make_qr_token(
            self.kiosk,
            token_hash='pre-cleanup-token'.ljust(64, '0'),
            issued_at=timezone.now() - datetime.timedelta(days=3),
            expires_at=timezone.now() - datetime.timedelta(days=2),
        )
        self.call_cleanup()

        issued = create_qr_token(self.kiosk)
        result = validate_qr_token_for_employee(self.employee, issued.raw_token)

        self.assertTrue(result.allowed)


class QRPortalTests(TestCase):
    def setUp(self):
        self.company = _make_company(
            attendance_qr_validation_enabled=True,
            attendance_ip_validation_enabled=False,
            require_attendance_gps_when_ip_disabled=False,
            require_attendance_selfie_when_ip_disabled=False,
        )
        self.schedule = _make_schedule(self.company)
        self.location = _make_location(self.company, ip_address='10.10.10.10')
        self.kiosk = _make_kiosk(self.company, self.location)
        self.user = User.objects.create_user('qr_portal_user', password='pass')
        self.employee = _make_employee(self.company, schedule=self.schedule, user=self.user)
        self.portal_url = reverse('attendance:attendance_portal')

    def _issued_token(self):
        return create_qr_token(self.kiosk).raw_token

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_qr_disabled_keeps_old_portal_behavior(self, _mock):
        self.company.attendance_qr_validation_enabled = False
        self.company.attendance_ip_validation_enabled = True
        self.company.save(update_fields=[
            'attendance_qr_validation_enabled',
            'attendance_ip_validation_enabled',
        ])
        self.location.ip_address = '127.0.0.1'
        self.location.save(update_fields=['ip_address'])

        self.client.login(username='qr_portal_user', password='pass')
        self.client.post(self.portal_url, {'action': 'time_in'})

        self.assertTrue(AttendanceRecord.objects.filter(employee=self.employee).exists())

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_qr_enabled_blocks_time_in_without_qr_token(self, _mock):
        self.client.login(username='qr_portal_user', password='pass')
        self.client.post(self.portal_url, {'action': 'time_in'})

        self.assertFalse(AttendanceRecord.objects.filter(employee=self.employee).exists())
        log = AttendancePortalLog.objects.filter(employee=self.employee, action='time_in').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.status, 'blocked')
        self.assertEqual(log.validation_method, 'BLOCKED_QR_MISSING')

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_qr_enabled_allows_time_in_with_live_qr_required_selfie_and_gps(self, _mock):
        self.company.require_attendance_gps_when_ip_disabled = True
        self.company.require_attendance_selfie_when_ip_disabled = True
        self.company.save(update_fields=[
            'require_attendance_gps_when_ip_disabled',
            'require_attendance_selfie_when_ip_disabled',
        ])
        self.client.login(username='qr_portal_user', password='pass')

        self.client.post(self.portal_url, {
            'action': 'time_in',
            'qr_token': self._issued_token(),
            'selfie_data': _selfie_payload(),
            'gps_latitude': '14.609100',
            'gps_longitude': '121.022300',
            'gps_accuracy': '10.20',
        })

        record = AttendanceRecord.objects.get(employee=self.employee)
        self.assertEqual(record.portal_location, self.location)
        log = AttendancePortalLog.objects.filter(employee=self.employee, action='time_in').first()
        self.assertEqual(log.status, 'success')
        self.assertEqual(log.validation_method, 'QR_IP_DISABLED_GPS_SELFIE')
        self.assertEqual(str(log.gps_latitude), '14.609100')
        self.assertIsNotNone(log.selfie_image)

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_qr_enabled_blocks_expired_qr_on_time_in(self, _mock):
        issued = create_qr_token(self.kiosk)
        issued.token.expires_at = issued.token.issued_at - datetime.timedelta(seconds=1)
        issued.token.save(update_fields=['expires_at'])

        self.client.login(username='qr_portal_user', password='pass')
        self.client.post(self.portal_url, {
            'action': 'time_in',
            'qr_token': issued.raw_token,
        })

        self.assertFalse(AttendanceRecord.objects.filter(employee=self.employee).exists())
        log = AttendancePortalLog.objects.filter(employee=self.employee, action='time_in').first()
        self.assertEqual(log.status, 'blocked')
        self.assertEqual(log.validation_method, 'BLOCKED_QR_EXPIRED')

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_ip_disabled_valid_qr_allows_wrong_detected_ip_and_logs_ip(self, _mock):
        self.client.login(username='qr_portal_user', password='pass')
        self.client.post(
            self.portal_url,
            {'action': 'time_in', 'qr_token': self._issued_token()},
            REMOTE_ADDR='203.0.113.88',
        )

        self.assertTrue(AttendanceRecord.objects.filter(employee=self.employee).exists())
        portal_log = AttendancePortalLog.objects.get(employee=self.employee, action='time_in')
        self.assertEqual(portal_log.ip_address, '203.0.113.88')
        qr_log = AttendanceQRScanLog.objects.filter(employee=self.employee, action='time_in').first()
        self.assertIsNotNone(qr_log)
        self.assertEqual(qr_log.ip_address, '203.0.113.88')

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_ip_enabled_blocks_qr_from_location_that_does_not_match_detected_ip(self, _mock):
        self.company.attendance_ip_validation_enabled = True
        self.company.save(update_fields=['attendance_ip_validation_enabled'])
        ip_matched_location = _make_location(
            self.company,
            name='IP Matched HQ',
            ip_address='127.0.0.1',
        )
        self.assertNotEqual(ip_matched_location.pk, self.location.pk)

        self.client.login(username='qr_portal_user', password='pass')
        self.client.post(self.portal_url, {
            'action': 'time_in',
            'qr_token': self._issued_token(),
        })

        self.assertFalse(AttendanceRecord.objects.filter(employee=self.employee).exists())
        log = AttendancePortalLog.objects.filter(employee=self.employee, action='time_in').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.status, 'blocked')
        self.assertEqual(log.validation_method, 'BLOCKED_QR_UNAUTHORIZED')

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_overnight_time_out_still_closes_carry_over_with_qr_enabled(self, _mock):
        yesterday = datetime.date.today() - datetime.timedelta(days=1)
        record = AttendanceRecord.objects.create(
            company=self.company,
            employee=self.employee,
            date=yesterday,
            time_in=datetime.time(22, 0),
            break_minutes=0,
            status='present',
            source='portal',
        )

        self.client.login(username='qr_portal_user', password='pass')
        self.client.post(self.portal_url, {
            'action': 'time_out',
            'qr_token': self._issued_token(),
        })

        record.refresh_from_db()
        self.assertIsNotNone(record.time_out)

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_flexible_time_out_under_required_hours_computes_undertime_not_blocked(self, _mock):
        self.employee.attendance_policy_type = Employee.ATTENDANCE_POLICY_FLEXIBLE
        self.employee.required_daily_hours = Decimal('8.00')
        self.employee.default_break_minutes = 0
        self.employee.save(update_fields=[
            'attendance_policy_type',
            'required_daily_hours',
            'default_break_minutes',
        ])
        today = datetime.date.today()
        record = AttendanceRecord.objects.create(
            company=self.company,
            employee=self.employee,
            date=today,
            time_in=datetime.time(8, 0),
            break_minutes=0,
            status='present',
            source='portal',
        )

        with patch('attendance.views._datetime') as mocked_datetime:
            mocked_datetime.now.return_value = datetime.datetime.combine(today, datetime.time(9, 0))
            self.client.login(username='qr_portal_user', password='pass')
            self.client.post(self.portal_url, {
                'action': 'time_out',
                'qr_token': self._issued_token(),
            })

        record.refresh_from_db()
        self.assertEqual(record.time_out, datetime.time(9, 0))
        self.assertEqual(record.computed_status, 'undertime')
        self.assertGreater(record.undertime_minutes, 0)
