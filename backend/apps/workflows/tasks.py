from celery import shared_task

from . import deadlines


@shared_task(name="workflows.check_deadlines", ignore_result=True)
def check_deadlines() -> None:
    deadlines.check()
