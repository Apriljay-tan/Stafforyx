"""
Shrink the SQLite database file after a large cleanup.

    python manage.py vacuum_sqlite

VACUUM only makes sense for SQLite, so this command no-ops (with a clear message)
on any other database engine. Run it manually after archiving/clearing — never
automatically during a web request, since VACUUM locks the database.
"""

from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = 'Run SQLite VACUUM to reclaim space after cleanup. Skips non-SQLite databases.'

    def handle(self, *args, **options):
        if connection.vendor != 'sqlite':
            self.stdout.write(
                f'Database engine is "{connection.vendor}", not sqlite — VACUUM skipped.'
            )
            return

        self.stdout.write('Running VACUUM on the SQLite database…')
        with connection.cursor() as cursor:
            cursor.execute('VACUUM;')
        self.stdout.write(self.style.SUCCESS('VACUUM complete. Database file compacted.'))
