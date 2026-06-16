"""
Generate a payroll archive Excel file from the command line (manual/server backup).

    python manage.py export_archive --company-id 3 \
        --date-from 2026-06-01 --date-to 2026-06-15 \
        --output D:/backups/june_h1.xlsx

This NEVER deletes anything. It writes the .xlsx and records an ArchiveBatch so
the matching data can later be cleared with ``cleanup_archived_data``.
"""

import os
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from companies.models import Company
from payroll.archive_services import (
    build_archive_workbook, collect_archive_querysets, count_archive_records,
    build_archive_filename,
)
from payroll.models import ArchiveBatch


def _parse_date(value, label):
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        raise CommandError(f'{label} must be in YYYY-MM-DD format.')


class Command(BaseCommand):
    help = 'Export payroll-related data for a company + date range to an .xlsx file.'

    def add_arguments(self, parser):
        parser.add_argument('--company-id', type=int, required=True)
        parser.add_argument('--date-from', required=True, help='YYYY-MM-DD')
        parser.add_argument('--date-to', required=True, help='YYYY-MM-DD')
        parser.add_argument('--output', help='Output .xlsx path. Defaults to the current directory.')

    def handle(self, *args, **options):
        try:
            company = Company.objects.get(pk=options['company_id'])
        except Company.DoesNotExist:
            raise CommandError(f"Company #{options['company_id']} does not exist.")

        date_from = _parse_date(options['date_from'], '--date-from')
        date_to = _parse_date(options['date_to'], '--date-to')
        if date_to < date_from:
            raise CommandError('--date-to must not be earlier than --date-from.')

        querysets = collect_archive_querysets(company, date_from, date_to)
        counts = count_archive_records(querysets)
        workbook = build_archive_workbook(
            querysets, company=company, date_from=date_from, date_to=date_to, counts=counts,
        )

        output = options.get('output') or build_archive_filename(company, date_from, date_to)
        output = os.path.abspath(output)
        os.makedirs(os.path.dirname(output) or '.', exist_ok=True)
        workbook.save(output)

        ArchiveBatch.objects.create(
            company=company, date_from=date_from, date_to=date_to,
            file_name=os.path.basename(output), file_path=output,
            payroll_count=counts.get('payroll_records', 0),
            attendance_count=counts.get('attendance_records', 0),
            portal_log_count=counts.get('portal_logs', 0),
            qr_log_count=counts.get('qr_logs', 0),
            overtime_count=counts.get('overtime_requests', 0),
            leave_count=counts.get('leave_requests', 0),
            ca_count=counts.get('ca_requests', 0),
            notes='Generated via export_archive management command.',
        )

        self.stdout.write(self.style.SUCCESS(f'Archive written to {output}'))
        for key, value in counts.items():
            self.stdout.write(f'  {key}: {value}')
