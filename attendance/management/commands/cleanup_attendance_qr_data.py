import datetime

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from attendance.models import AttendanceQRScanLog, AttendanceQRToken
from companies.models import Company


def _retention_days(company, field_name, default, days_override):
    if days_override is not None:
        return days_override
    value = getattr(company, field_name, default)
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = default
    return max(value, 1)


def _delete_count(queryset, dry_run):
    count = queryset.count()
    if dry_run or count == 0:
        return count, 0
    deleted_total, breakdown = queryset.delete()
    model_label = queryset.model._meta.label
    return count, breakdown.get(model_label, 0) or min(deleted_total, count)


class Command(BaseCommand):
    help = (
        'Delete old rotating QR attendance tokens and scan logs according to '
        'company retention settings. Attendance, payroll, and employee records '
        'are never deleted.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', default=False)
        parser.add_argument('--company-id', type=int, help='Only process one company id.')
        parser.add_argument('--tokens-only', action='store_true', default=False)
        parser.add_argument('--scan-logs-only', action='store_true', default=False)
        parser.add_argument('--days', type=int, help='Override retention days for selected cleanup data.')
        parser.add_argument(
            '--delete-expired-tokens',
            action='store_true',
            default=False,
            help='Delete eligible expired QR tokens even if the company auto-delete setting is off.',
        )
        parser.add_argument(
            '--delete-old-scan-logs',
            action='store_true',
            default=False,
            help='Delete eligible QR scan logs even if the company auto-delete setting is off.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        company_id = options.get('company_id')
        tokens_only = options['tokens_only']
        scan_logs_only = options['scan_logs_only']
        days_override = options.get('days')
        force_tokens = options['delete_expired_tokens']
        force_scan_logs = options['delete_old_scan_logs']

        if tokens_only and scan_logs_only:
            raise CommandError('Use either --tokens-only or --scan-logs-only, not both.')
        if days_override is not None and days_override < 0:
            raise CommandError('--days must be 0 or greater.')

        companies = Company.objects.order_by('name')
        if company_id is not None:
            companies = companies.filter(pk=company_id)
            if not companies.exists():
                raise CommandError(f'Company #{company_id} does not exist.')

        process_tokens = not scan_logs_only
        process_scan_logs = not tokens_only
        now = timezone.now()

        companies_scanned = 0
        token_eligible = 0
        token_deleted = 0
        scan_log_eligible = 0
        scan_log_deleted = 0

        self.stdout.write(
            f"Starting cleanup_attendance_qr_data ({'dry-run' if dry_run else 'live'})"
        )
        if company_id is not None:
            self.stdout.write(f'Company filter: #{company_id}')
        if days_override is not None:
            self.stdout.write(f'Retention override: {days_override} day(s)')

        for company in companies.iterator(chunk_size=100):
            companies_scanned += 1

            if process_tokens and (
                force_tokens or getattr(company, 'attendance_auto_delete_qr_tokens', True)
            ):
                token_days = _retention_days(
                    company,
                    'attendance_qr_token_retention_days',
                    1,
                    days_override,
                )
                token_cutoff = now - datetime.timedelta(days=token_days)
                queryset = AttendanceQRToken.objects.filter(
                    company=company,
                    expires_at__lt=token_cutoff,
                )
                eligible, deleted = _delete_count(queryset, dry_run)
                token_eligible += eligible
                token_deleted += deleted

            if process_scan_logs and (
                force_scan_logs or getattr(company, 'attendance_auto_delete_qr_scan_logs', False)
            ):
                scan_log_days = _retention_days(
                    company,
                    'attendance_qr_scan_log_retention_days',
                    90,
                    days_override,
                )
                scan_log_cutoff = now - datetime.timedelta(days=scan_log_days)
                queryset = AttendanceQRScanLog.objects.filter(
                    company=company,
                    created_at__lt=scan_log_cutoff,
                )
                eligible, deleted = _delete_count(queryset, dry_run)
                scan_log_eligible += eligible
                scan_log_deleted += deleted

        self.stdout.write('-' * 60)
        self.stdout.write(f'Companies scanned       : {companies_scanned}')
        self.stdout.write(f'QR tokens eligible      : {token_eligible}')
        self.stdout.write(f'QR tokens deleted       : {token_deleted}')
        self.stdout.write(f'QR scan logs eligible   : {scan_log_eligible}')
        self.stdout.write(f'QR scan logs deleted    : {scan_log_deleted}')
        self.stdout.write(f"Dry run: {'yes' if dry_run else 'no'}")
        self.stdout.write('-' * 60)
