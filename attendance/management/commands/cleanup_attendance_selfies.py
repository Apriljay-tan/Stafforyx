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
        'Delete old attendance portal selfie files based on retention days while '
        'keeping AttendancePortalLog rows intact.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            default=False,
            help='Show what would be deleted without deleting files or updating rows.',
        )
        parser.add_argument(
            '--days',
            type=int,
            help='Override retention days for all companies (0 means delete immediately).',
        )
        parser.add_argument(
            '--company-id',
            type=int,
            help='Only process selfie logs for one company id.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        days_override = options.get('days')
        company_id = options.get('company_id')

        if days_override is not None and days_override < 0:
            raise CommandError('--days must be 0 or greater.')

        company = None
        if company_id is not None:
            try:
                company = Company.objects.get(pk=company_id)
            except Company.DoesNotExist as exc:
                raise CommandError(f'Company #{company_id} does not exist.') from exc

        qs = (
            AttendancePortalLog.objects
            .select_related('company')
            .filter(selfie_image__isnull=False)
            .exclude(selfie_image='')
            .order_by('created_at')
        )

        if company is not None:
            qs = qs.filter(company=company)

        scanned = 0
        deleted = 0
        skipped = 0
        freed_bytes = 0

        now = timezone.now()

        self.stdout.write(
            f"Starting cleanup_attendance_selfies ({'dry-run' if dry_run else 'live'})"
        )
        if company is not None:
            self.stdout.write(f'Company filter: {company.name} (#{company.pk})')
        if days_override is not None:
            self.stdout.write(f'Retention override: {days_override} day(s)')

        for log in qs.iterator(chunk_size=200):
            scanned += 1

            retention_days = days_override
            if retention_days is None:
                if log.company and getattr(log.company, 'attendance_selfie_retention_days', None):
                    retention_days = int(log.company.attendance_selfie_retention_days)
                else:
                    retention_days = 30

            cutoff = now - datetime.timedelta(days=retention_days)
            if log.created_at > cutoff:
                skipped += 1
                continue

            selfie_field = log.selfie_image
            if not selfie_field:
                skipped += 1
                continue

            storage = selfie_field.storage
            selfie_name = selfie_field.name

            file_size = 0
            exists = storage.exists(selfie_name)
            if exists:
                try:
                    file_size = storage.size(selfie_name)
                except Exception:
                    file_size = 0

            if dry_run:
                deleted += 1
                freed_bytes += file_size
                continue

            try:
                if exists:
                    storage.delete(selfie_name)
                log.selfie_image = ''
                log.save(update_fields=['selfie_image'])
                deleted += 1
                freed_bytes += file_size
            except Exception as exc:
                skipped += 1
                self.stderr.write(
                    self.style.ERROR(f'Failed to clean log #{log.pk}: {exc}')
                )

        self.stdout.write('-' * 56)
        self.stdout.write(f'Scanned logs            : {scanned}')
        self.stdout.write(f'Deleted selfie entries  : {deleted}')
        self.stdout.write(f'Skipped                 : {skipped}')
        self.stdout.write(f'Estimated space freed   : {_bytes_to_human(freed_bytes)}')
        if dry_run:
            self.stdout.write(self.style.WARNING('Dry-run mode: no files or database rows were changed.'))
        self.stdout.write('-' * 56)
