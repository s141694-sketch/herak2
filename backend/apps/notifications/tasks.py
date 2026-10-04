from celery import shared_task

from . import digest


@shared_task(name="notifications.daily_digest", ignore_result=True)
def daily_digest() -> None:
    digest.send_all()
