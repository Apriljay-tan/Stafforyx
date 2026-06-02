from django.apps import AppConfig


class OvertimeConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'overtime'
    verbose_name = 'Overtime'

    def ready(self):
        # Import signal handlers so they are registered.
        from . import signals  # noqa: F401
