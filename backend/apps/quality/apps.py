from django.apps import AppConfig


class QualityConfig(AppConfig):
    name = "apps.quality"
    label = "quality"
    verbose_name = "Quality"

    def ready(self):
        from . import receivers  # noqa: F401
