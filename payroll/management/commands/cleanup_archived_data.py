"""
Delete only the records covered by an existing ArchiveBatch (manual/server use).

    python manage.py cleanup_archived_data --archive-batch-id 5
    python manage.py cleanup_archived_data --archive-batch-id 5 --dry-run

Safety:
  * Requires an existing ArchiveBatch (i.e. an export already happened).
  * Refuses to clear a batch whose range includes today or the future unless
    --force is given (protects the active payroll period).
  * Never deletes employees, companies, users, settings, locations, or periods.
"""

from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from payroll.archive_services import collect_archive_querysets, count_archive_records, perform_cleanup
from payroll.models import ArchiveBatch


class Command(BaseCommand):
    help = 'Clear the records included in an ArchiveBatch. Export must already exist.'

    def add_arguments(self, parser):
        parser.add_argument('--archive-batch-id', type=int, required=True)
        parser.add_argument('--dry-run', action='store_true', default=False)
        parser.add_argument(
            '--force', action='store_true', default=False,
            help='Allow clearing even if the range includes today/future.',
        )

    def handle(self, *args, **options):
        try:
            batch = ArchiveBatch.objects.select_related('company', 'payroll_period').get(
                pk=options['archive_batch_id']
            )
        except ArchiveBatch.DoesNotExist:
            raise CommandError(f"ArchiveBatch #{options['archive_batch_id']} does not exist.")

        if batch.is_cleared:
            raise CommandError('This archive batch has already been cleared.')

        if batch.date_to >= date.today() and not options['force']:
            raise CommandError(
                'Archive range includes today or a future date. Refusing to clear the '
                'active period. Re-run with --force only if you are certain.'
            )

        querysets = collect_archive_querysets(
            batch.company, batch.date_from, batch.date_to, batch.payroll_period
        )
        counts = count_archive_records(querysets)

        if options['dry_run']:
            self.stdout.write(f'Dry run for ArchiveBatch #{batch.pk} ({batch.company.name}):')
            for key, value in counts.items():
                self.stdout.write(f'  {key}: {value}')
            self.stdout.write(self.style.WARNING('Dry run — nothing deleted.'))
            return

        cleared = perform_cleanup(batch)
        batch.cleared_counts = cleared
        batch.is_cleared = True
        batch.cleared_at = timezone.now()
        batch.save(update_fields=['cleared_counts', 'is_cleared', 'cleared_at'])

        self.stdout.write(self.style.SUCCESS(
            f'Cleared {sum(cleared.values())} record(s) for ArchiveBatch #{batch.pk}.'
        ))
        for key, value in cleared.items():
            self.stdout.write(f'  {key}: {value}')
