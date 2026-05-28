"""
python manage.py generate_employee_schedules \
    --company-id 1 \
    --shift-id 2 \
    --date-from 2026-06-01 \
    --date-to 2026-06-07 \
    [--employee-id EMP-001] \
    [--weekdays 0,1,2,3,4] \
    [--overwrite]

Assigns a ShiftTemplate to employees over a date range, creating
EmployeeDailySchedule rows. Existing rows are skipped unless --overwrite
is passed.
"""

import datetime

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from attendance.models import EmployeeDailySchedule, ShiftTemplate
from companies.models import Company
from employees.models import Employee


def _parse_date(value, option_name):
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        raise CommandError(f'--{option_name}: "{value}" is not a valid YYYY-MM-DD date.')


class Command(BaseCommand):
    help = 'Bulk-assign a shift template to employees over a date range.'

    def add_arguments(self, parser):
        parser.add_argument('--company-id', required=True, type=int)
        parser.add_argument('--shift-id', required=True, type=int)
        parser.add_argument('--date-from', required=True)
        parser.add_argument('--date-to', required=True)
        parser.add_argument(
            '--employee-id',
            help='Limit to one employee by employee_id (e.g. EMP-001). '
                 'Omit to target all active employees in the company.',
        )
        parser.add_argument(
            '--weekdays',
            help='Comma-separated weekday numbers (0=Mon … 6=Sun). '
                 'Omit to generate for every day in the range.',
        )
        parser.add_argument(
            '--overwrite',
            action='store_true',
            default=False,
            help='Overwrite (update_or_create) existing schedule entries.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            default=False,
        )

    def handle(self, *args, **options):
        try:
            company = Company.objects.get(pk=options['company_id'])
        except Company.DoesNotExist:
            raise CommandError(f'Company #{options["company_id"]} not found.')

        try:
            shift = ShiftTemplate.objects.get(pk=options['shift_id'], company=company)
        except ShiftTemplate.DoesNotExist:
            raise CommandError(
                f'ShiftTemplate #{options["shift_id"]} not found in {company.name}.'
            )

        date_from = _parse_date(options['date_from'], 'date-from')
        date_to = _parse_date(options['date_to'], 'date-to')
        if date_to < date_from:
            raise CommandError('--date-to must be on or after --date-from.')

        weekdays = None
        if options.get('weekdays'):
            try:
                weekdays = [int(d.strip()) for d in options['weekdays'].split(',')]
                if not all(0 <= d <= 6 for d in weekdays):
                    raise ValueError
            except ValueError:
                raise CommandError('--weekdays must be comma-separated integers 0–6.')

        employees = Employee.objects.filter(company=company, status='active')
        if options.get('employee_id'):
            employees = employees.filter(employee_id=options['employee_id'])
            if not employees.exists():
                raise CommandError(
                    f'Employee "{options["employee_id"]}" not found in {company.name}.'
                )

        dry_run = options['dry_run']
        overwrite = options['overwrite']
        created = updated = skipped = 0

        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN — no changes will be saved.\n'))

        with transaction.atomic():
            current = date_from
            while current <= date_to:
                if weekdays is None or current.weekday() in weekdays:
                    for emp in employees:
                        if overwrite:
                            if not dry_run:
                                _, was_created = EmployeeDailySchedule.objects.update_or_create(
                                    employee=emp,
                                    schedule_date=current,
                                    defaults=dict(
                                        company=company,
                                        shift_template=shift,
                                        is_rest_day=False,
                                        source='generated',
                                    ),
                                )
                            else:
                                was_created = not EmployeeDailySchedule.objects.filter(
                                    employee=emp, schedule_date=current
                                ).exists()
                            if was_created:
                                created += 1
                                self.stdout.write(f'  CREATE {emp.employee_id} {current}')
                            else:
                                updated += 1
                                self.stdout.write(f'  UPDATE {emp.employee_id} {current}')
                        else:
                            exists = EmployeeDailySchedule.objects.filter(
                                employee=emp, schedule_date=current
                            ).exists()
                            if not exists:
                                if not dry_run:
                                    EmployeeDailySchedule.objects.create(
                                        company=company,
                                        employee=emp,
                                        schedule_date=current,
                                        shift_template=shift,
                                        is_rest_day=False,
                                        source='generated',
                                    )
                                created += 1
                                self.stdout.write(f'  CREATE {emp.employee_id} {current}')
                            else:
                                skipped += 1
                current += datetime.timedelta(days=1)

            if dry_run:
                transaction.set_rollback(True)

        self.stdout.write('\n' + '-' * 50)
        self.stdout.write(f'  Company   : {company.name}')
        self.stdout.write(f'  Shift     : {shift.name}')
        self.stdout.write(f'  Range     : {date_from} – {date_to}')
        self.stdout.write(self.style.SUCCESS(f'  Created   : {created}'))
        if updated:
            self.stdout.write(self.style.WARNING(f'  Updated   : {updated}'))
        self.stdout.write(f'  Skipped   : {skipped}')
        if dry_run:
            self.stdout.write(self.style.WARNING('\n  (Dry run — nothing was saved)'))
        self.stdout.write('-' * 50)
