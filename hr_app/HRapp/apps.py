from django.apps import AppConfig


class HrappConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'hr_app.HRapp'

    def ready(self):
        from . import signals  # noqa
