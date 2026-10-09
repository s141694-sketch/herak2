import os

from celery import Celery, signals

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

app = Celery("harak2")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@signals.setup_logging.connect
def use_django_logging(**kwargs):
    """The worker and beat log as the web process does, from settings.LOGGING (D101).

    Without a receiver here, Celery removes the handler of the "celery" logger, which does not propagate, so every
    worker log line (failed tasks included) was lost, and so was what tasks print, such as the console email
    backend's emails. With one, Celery leaves logging and sys.stdout as they are.
    """
    from django.conf import settings
    from django.utils.log import configure_logging

    configure_logging(settings.LOGGING_CONFIG, settings.LOGGING)
