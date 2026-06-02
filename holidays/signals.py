import datetime

from django.db.models.signals import post_save
from django.dispatch import receiver

from companies.models import Company


@receiver(post_save, sender=Company, dispatch_uid="holidays_seed_on_company_create")
def seed_holidays_for_new_company(sender, instance, created, **kwargs):
    if not created:
        return
    # Local import avoids app-loading issues at import time.
    from .seeding import seed_default_holidays
    seed_default_holidays(instance, datetime.date.today().year)
