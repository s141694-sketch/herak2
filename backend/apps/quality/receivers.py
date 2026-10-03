"""The engine follows the content: a light run after each change to a draft, a full run at submission."""

from django.db import transaction
from django.dispatch import receiver

from apps.programs import lifecycle
from apps.programs.models import ProgramVersion
from apps.programs.signals import content_changed

from . import services
from .models import QualityReport

S = ProgramVersion.Status


@receiver(content_changed)
def run_after_change(sender, version, **kwargs):
    version_id = version.pk

    def request():
        current = ProgramVersion.objects.filter(pk=version_id, status=S.DRAFT).first()
        if current is not None:
            services.request_run(current, QualityReport.Run.LIGHT)

    transaction.on_commit(request)


@receiver(lifecycle.left_draft)
def run_at_submission(sender, version, target, **kwargs):
    if target != S.SUBMITTED:
        return
    version_id = version.pk
    transaction.on_commit(
        lambda: services.request_run(ProgramVersion.objects.get(pk=version_id), QualityReport.Run.FULL, final=True)
    )
