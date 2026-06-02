import datetime

from django.core.management.base import BaseCommand

from companies.models import Company
from holidays.seeding import seed_default_holidays


class Command(BaseCommand):
    help = "Seed default Philippine holidays for companies."

    def add_arguments(self, parser):
        parser.add_argument("--company", type=int, default=None,
                            help="Company ID. Omit to seed all companies.")
        parser.add_argument("--year", type=int, default=datetime.date.today().year,
                            help="Year to seed (default: current year).")

    def handle(self, *args, **options):
        year = options["year"]
        if options["company"]:
            companies = Company.objects.filter(pk=options["company"])
        else:
            companies = Company.objects.all()

        total = 0
        for company in companies:
            created = seed_default_holidays(company, year)
            total += created
            self.stdout.write(f"{company.name}: +{created} holiday(s) for {year}")
        self.stdout.write(self.style.SUCCESS(f"Done. {total} holiday(s) created."))
