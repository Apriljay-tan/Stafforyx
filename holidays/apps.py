from django.apps import AppConfig


class HolidaysConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "holidays"
    verbose_name = "Holidays"

    def ready(self):
        # Import signal handlers (registered in Task 4).
        from . import signals  # noqa: F401
