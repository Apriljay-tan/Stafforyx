"""
python manage.py fix_attendance_overtime_status

Find historical attendance rows where Request Required employees were saved
with payable overtime but have no approved OvertimeRequest for that date, then
recompute them with the current attendance policy.

Target records match ALL of:
  A. employee.overtime_policy is request_required (or legacy management_review)
  B. overtime_minutes > 0 OR computed_status = 'overtime'
  C. no approved/auto_approved OvertimeRequest for that employee + date

Recompute sets payable overtime_minutes/overtime_hours to 0 when no approval
exists, keeps actual_overtime_minutes for audit, and clears the Overtime status.

Options
-------
--dry-run               Preview matches and before/after values; do not save.
--employee-id STF-001   Limit to one employee.
--date-from YYYY-MM-DD  Lower bound (inclusive) on record date.
--date-to   YYYY-MM-DD  Upper bound (inclusive) on record date.

Example (safe preview first):
  python manage.py fix_attendance_overtime_status --dry-run
  python manage.py fix_attendance_overtime_status
"""

import datetime

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Exists, OuterRef, Q

from attendance.management.commands.recompute_attendance import (
    _DryRunRollback,
    _snapshot,
    _TRACKED,
)
from attendance.models import AttendanceRecord
from attendance.services import compute_attendance
from overtime.models import OvertimeRequest

REQUEST_REQUIRED_POLICIES = ('request_required', 'management_review')


def _parse_date(value, option_name):
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        raise CommandError(
            f'--{option_name}: "{value}" is not a valid date (expected YYYY-MM-DD).'
        )


def build_mismarked_request_required_queryset(
    *,
    employee_id=None,
    date_from=None,
    date_to=None,
):
    """
    Return attendance rows that incorrectly carry payable overtime for Request
    Required employees without an approved overtime request on that date.
    """
    approved_request_exists = OvertimeRequest.objects.filter(
        employee_id=OuterRef('employee_id'),
        date=OuterRef('date'),
        status__in=['approved', 'auto_approved'],
    )

    qs = (
        AttendanceRecord.objects
        .filter(employee__overtime_policy__in=REQUEST_REQUIRED_POLICIES)
        .filter(Q(overtime_minutes__gt=0) | Q(computed_status='overtime'))
        .exclude(Exists(approved_request_exists))
        .select_related('employee', 'employee__work_schedule', 'company')
        .order_by('date', 'employee__employee_id')
    )

    if employee_id:
        qs = qs.filter(employee__employee_id=employee_id)
    if date_from:
        qs = qs.filter(date__gte=date_from)
    if date_to:
        qs = qs.filter(date__lte=date_to)

    return qs


class Command(BaseCommand):
    help = (
        'Recompute Request Required attendance rows saved with payable overtime '
        'but no approved overtime request.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            default=False,
            help='Show matches and planned changes without saving.',
        )
        parser.add_argument(
            '--employee-id',
            metavar='EMPLOYEE_ID',
            help='Limit to one employee (employee_id field).',
        )
        parser.add_argument(
            '--date-from',
            metavar='YYYY-MM-DD',
            help='Only records on or after this date.',
        )
        parser.add_argument(
            '--date-to',
            metavar='YYYY-MM-DD',
            help='Only records on or before this date.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        employee_id = options.get('employee_id')
        date_from = (
            _parse_date(options['date_from'], 'date-from')
            if options.get('date_from') else None
        )
        date_to = (
            _parse_date(options['date_to'], 'date-to')
            if options.get('date_to') else None
        )

        qs = build_mismarked_request_required_queryset(
            employee_id=employee_id,
            date_from=date_from,
            date_to=date_to,
        )

        total = qs.count()
        self.stdout.write(
            'Selection criteria:\n'
            '  A. employee.overtime_policy in '
            f'{list(REQUEST_REQUIRED_POLICIES)!r}\n'
            '  B. overtime_minutes > 0 OR computed_status = '
            "'overtime'\n"
            '  C. no approved/auto_approved OvertimeRequest for employee+date'
        )
        if employee_id:
            self.stdout.write(f'  filter employee_id = {employee_id!r}')
        if date_from:
            self.stdout.write(f'  filter date >= {date_from.isoformat()!r}')
        if date_to:
            self.stdout.write(f'  filter date <= {date_to.isoformat()!r}')
        self.stdout.write(f'\nMatched records: {total}\n')

        if total == 0:
            self.stdout.write('Nothing to update.')
            return

        counters = {'updated': 0, 'unchanged': 0, 'errors': 0}

        if dry_run:
            self.stdout.write(
                self.style.WARNING('DRY RUN — no changes will be saved.\n')
            )
            self._run_dry(qs, counters)
        else:
            self.stdout.write(f'Recomputing {total} mismarked record(s)...\n')
            for record in qs.iterator(chunk_size=200):
                self._process_one(record, counters)

        self._print_summary(total, counters, dry_run)

    def _run_dry(self, qs, counters):
        try:
            with transaction.atomic():
                for record in qs.iterator(chunk_size=200):
                    self._process_one(record, counters, show_diff=True)
                raise _DryRunRollback()
        except _DryRunRollback:
            pass

    def _process_one(self, record, counters, show_diff=False):
        try:
            before = _snapshot(record)
            compute_attendance(record)
            after = _snapshot(record)

            if before != after:
                counters['updated'] += 1
                if show_diff:
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
                    if before['actual_overtime_minutes'] == after['actual_overtime_minutes']:
                        self.stdout.write(
                            '    actual_overtime_minutes: '
                            f'{after["actual_overtime_minutes"]!r} (unchanged)'
                        )
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

    def _print_summary(self, total, counters, dry_run):
        sep = '-' * 52
        self.stdout.write(f'\n{sep}')
        self.stdout.write(f'  Matched   : {total}')
        self.stdout.write(
            self.style.SUCCESS(f'  Updated   : {counters["updated"]}')
            if counters['updated'] else '  Updated   : 0'
        )
        self.stdout.write(f'  Unchanged : {counters["unchanged"]}')
        if counters['errors']:
            self.stdout.write(
                self.style.ERROR(f'  Errors    : {counters["errors"]}')
            )
        if dry_run:
            self.stdout.write(
                self.style.WARNING('\n  (Dry run — no changes were saved)')
            )
        self.stdout.write(sep)
