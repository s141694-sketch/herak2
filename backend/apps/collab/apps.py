from django.apps import AppConfig


class CollabConfig(AppConfig):
    name = "apps.collab"
    label = "collab"

    def ready(self):
        from . import signals  # noqa: F401
