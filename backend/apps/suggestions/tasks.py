from celery import shared_task

from apps.tenancy.context import organization_context

from . import services
from .models import Suggestion


@shared_task(name="suggestions.run")
def run_suggestion(suggestion_id: int) -> None:
    organization_id = (
        Suggestion.all_organizations.filter(pk=suggestion_id).values_list("organization_id", flat=True).first()
    )
    if organization_id is None:
        return
    with organization_context(organization_id):
        services.run(suggestion_id)
