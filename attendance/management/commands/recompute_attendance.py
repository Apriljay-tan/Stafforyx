"""
python manage.py recompute_attendance

Recompute derived attendance fields (total_hours, overtime_hours,
late_minutes, undertime_minutes, overtime_minutes, actual_overtime_minutes,
total_work_minutes, computed_status) for existing AttendanceRecord rows using
the current attendance calculation logic. This re-applies the company/employee
overtime counting rule, so old records get counted overtime and a preserved
actual_overtime_minutes value.

Options
-------
--dry-run               Show what would change; do not persist.
--employee-id STF-001   Limit to one employee (uses employee_id field).
--date-from YYYY-MM-DD  Lower bound (inclusive) on record date.
--date-to   YYYY-MM-DD  Upper bound (inclusive) on record date.
"""

import datetime

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from attendance.models import AttendanceRecord
from attendance.services import compute_attendance

# These are the fields compute_attendance writes; we track their before/after.
_TRACKED = [
    'late_minutes',
    'undertime_minutes',
    'actual_overtime_minutes',
    'overtime_minutes',
    'total_work_minutes',
    'total_hours',
    'overtime_hours',
    'computed_status',
]


class _DryRunRollback(Exception):
    """Raised inside an atomic block to force a rollback without crashing."""


def _snapshot(record):
    return {f: getattr(record, f) for f in _TRACKED}


def _parse_date(value, option_name):
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        raise CommandError(
            f'--{option_name}: "{value}" is not a valid date (expected YYYY-MM-DD).'
        )


class Command(BaseCommand):
    help = (
        'Recompute attendance derived fields for existing records '
        '(total_hours, overtime_hours, late_minutes, etc.).'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            default=False,
            help='Show what would change without saving anything.',
        )
        parser.add_argument(
            '--employee-id',
            metavar='EMPLOYEE_ID',
            help='Recompute only records for this employee (e.g. STF-001).',
        )
        parser.add_argument(
            '--date-from',
            metavar='YYYY-MM-DD',
            help='Recompute records on or after this date.',
        )
        parser.add_argument(
            '--date-to',
            metavar='YYYY-MM-DD',
            help='Recompute records on or before this date.',
        )

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        employee_id_filter = options.get('employee_id')
        date_from = _parse_date(options['date_from'], 'date-from') if options.get('date_from') else None
        date_to   = _parse_date(options['date_to'],   'date-to')   if options.get('date_to')   else None

        qs = (
            AttendanceRecord.objects
            .select_related('employee', 'employee__work_schedule', 'company')
            .order_by('date', 'employee__employee_id')
        )

        if employee_id_filter:
            qs = qs.filter(employee__employee_id=employee_id_filter)
            if not qs.exists():
                raise CommandError(
                    f'No attendance records found for employee ID "{employee_id_filter}".'
                )

        if date_from:
            qs = qs.filter(date__gte=date_from)

        if date_to:
            qs = qs.filter(date__lte=date_to)

        total = qs.count()

        if total == 0:
            self.stdout.write('No records match the given filters. Nothing to do.')
            return

        if dry_run:
            self.stdout.write(
                self.style.WARNING(f'DRY RUN -- no changes will be saved ({total} record(s) to scan)\n')
            )
        else:
            self.stdout.write(f'Recomputing {total} record(s)...\n')

        counters = {'updated': 0, 'unchanged': 0, 'errors': 0}

        if dry_run:
            self._run_dry(qs, counters)
        else:
            self._run_live(qs, counters)

        self._print_summary(total, counters, dry_run)

    # ------------------------------------------------------------------
    # Execution paths
    # ------------------------------------------------------------------

    def _run_live(self, qs, counters):
        for record in qs.iterator(chunk_size=200):
            self._process_one(record, counters, dry_run=False)

    def _run_dry(self, qs, counters):
        """
        Run inside a transaction that is always rolled back so no changes
        reach the database, while still exercising the real computation path.
        """
        try:
            with transaction.atomic():
                for record in qs.iterator(chunk_size=200):
                    self._process_one(record, counters, dry_run=True)
                raise _DryRunRollback()
        except _DryRunRollback:
            pass

    # ------------------------------------------------------------------
    # Per-record logic
    # ------------------------------------------------------------------

    def _process_one(self, record, counters, *, dry_run):
        try:
            before = _snapshot(record)
            compute_attendance(record)
            after = _snapshot(record)

            if before != after:
                counters['updated'] += 1
                if dry_run:
                    self._print_diff(record, before, after)
            else:
                counters['unchanged'] += 1

        except Exception as exc:
            counters['errors'] += 1
            self.stderr.write(
                self.style.ERROR(
                    f'  ERROR — record #{record.pk} '
                    f'({record.employee} on {record.date}): {exc}'
                )
            )

    # ------------------------------------------------------------------
    # Output helpers
    # ------------------------------------------------------------------

    def _print_diff(self, record, before, after):
        self.stdout.write(
            f'  Would update #{record.pk}: '
            f'{record.employee.employee_id} {record.employee.full_name} '
            f'on {record.date}'
        )
        for field in _TRACKED:
            if before[field] != after[field]:
                self.stdout.write(
                    f'    {field}: {before[field]!r} → {after[field]!r}'
                )

    def _print_summary(self, total, counters, dry_run):
        sep = '-' * 52
        self.stdout.write(f'\n{sep}')
        self.stdout.write(f'  Scanned   : {total}')
        self.stdout.write(
            self.style.SUCCESS(f'  Updated   : {counters["updated"]}')
            if counters['updated'] else f'  Updated   : 0'
        )
        self.stdout.write(f'  Unchanged : {counters["unchanged"]}')
        if counters['errors']:
            self.stdout.write(
                self.style.ERROR(f'  Errors    : {counters["errors"]}')
            )
        if dry_run:
            self.stdout.write(
                self.style.WARNING('\n  (Dry run -- no changes were saved)')
            )
        self.stdout.write(sep)
