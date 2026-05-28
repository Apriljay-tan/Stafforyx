import datetime

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from attendance.models import AttendancePortalLog
from companies.models import Company


def _bytes_to_human(num_bytes):
    units = ['B', 'KB', 'MB', 'GB', 'TB']
    size = float(num_bytes or 0)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == 'B':
                return f'{int(size)} {unit}'
            return f'{size:.2f} {unit}'
        size /= 1024.0
    return f'{num_bytes} B'


class Command(BaseCommand):
    help = (
        'Delete old AttendancePortalLog records and attached selfie files safely. '
        'Attendance records, payroll records, and core HR data are not deleted.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', default=False)
        parser.add_argument('--company-id', type=int, help='Only process logs for one company id.')
        parser.add_argument('--days', type=int, help='Delete logs older than N days (override).')
        parser.add_argument(
            '--action',
            choices=[choice[0] for choice in AttendancePortalLog.ACTION_CHOICES],
            help='Only cleanup logs with this action key (page_open, time_in, time_out, blocked).',
        )
        parser.add_argument(
            '--delete-page-opened-only',
            action='store_true',
            default=False,
            help='Shortcut for --action page_open.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        company_id = options.get('company_id')
        days_override = options.get('days')
        action = options.get('action')
        page_open_only = options.get('delete_page_opened_only')

        if page_open_only and action:
            raise CommandError('Use either --action or --delete-page-opened-only, not both.')
        if page_open_only:
            action = 'page_open'

        if days_override is not None and days_override < 0:
            raise CommandError('--days must be 0 or greater.')

        company = None
        if company_id is not None:
            try:
                company = Company.objects.get(pk=company_id)
            except Company.DoesNotExist as exc:
                raise CommandError(f'Company #{company_id} does not exist.') from exc

        queryset = AttendancePortalLog.objects.select_related('company').order_by('created_at')
        if company is not None:
            queryset = queryset.filter(company=company)
        if action:
            queryset = queryset.filter(action=action)

        scanned = 0
        eligible = 0
        deleted = 0
        skipped = 0
        estimated_freed_bytes = 0

        now = timezone.now()

        mode = 'dry-run' if dry_run else 'live'
        self.stdout.write(f'Starting cleanup_attendance_portal_logs ({mode})')
        if company is not None:
            self.stdout.write(f'Company filter: {company.name} (#{company.pk})')
        if action:
            self.stdout.write(f'Action filter: {action}')
        if days_override is not None:
            self.stdout.write(f'Retention override: {days_override} day(s)')

        to_delete_ids = []

        for log in queryset.iterator(chunk_size=200):
            scanned += 1

            retention_days = days_override
            if retention_days is None:
                company_obj = log.company
                if company_obj is None:
                    retention_days = 30
                else:
                    if not company_obj.attendance_auto_delete_portal_logs:
                        skipped += 1
                        continue
                    retention_days = int(getattr(company_obj, 'attendance_portal_log_retention_days', 30) or 30)

            cutoff = now - datetime.timedelta(days=retention_days)
            if log.created_at >= cutoff:
                skipped += 1
                continue

            eligible += 1
            to_delete_ids.append(log.pk)

            if log.selfie_image:
                try:
                    estimated_freed_bytes += log.selfie_image.storage.size(log.selfie_image.name)
                except Exception:
                    pass

        if dry_run:
            deleted = 0
        else:
            if to_delete_ids:
                deleted_total, breakdown = AttendancePortalLog.objects.filter(pk__in=to_delete_ids).delete()
                deleted = breakdown.get('attendance.AttendancePortalLog', 0) or min(deleted_total, len(to_delete_ids))

        self.stdout.write('-' * 60)
        self.stdout.write(f'Scanned logs                 : {scanned}')
        self.stdout.write(f'Eligible for deletion        : {eligible}')
        self.stdout.write(f'Deleted portal logs          : {deleted}')
        self.stdout.write(f'Skipped                      : {skipped}')
        self.stdout.write(f'Estimated selfie space freed : {_bytes_to_human(estimated_freed_bytes)}')
        if dry_run:
            self.stdout.write(self.style.WARNING('Dry-run mode: no records/files were deleted.'))
        self.stdout.write('-' * 60)
