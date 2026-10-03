from celery import shared_task

from . import services


@shared_task(name="quality.run_report", ignore_result=True)
def run_report(report_id: int, run_id: str) -> None:
    services.execute_run(report_id, run_id)


@shared_task(name="quality.run_ai_layer", ignore_result=True)
def run_ai_layer(report_id: int, run_id: str) -> None:
    services.run_ai(report_id, run_id)
