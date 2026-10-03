"""A live save and a submission of the same draft never interleave (review finding: saves took no lock)."""

import threading
import time

import pytest
from django.db import close_old_connections, connection, transaction

from apps.programs.models import Block, ProgramVersion
from apps.tenancy.context import organization_context

from .test_documents import doc, rows_for, service, url, world  # noqa: F401 - the fixture is used below

S = ProgramVersion.Status


@pytest.mark.django_db(transaction=True)
def test_a_save_that_waits_on_a_submission_is_refused_once_it_commits(world):  # noqa: F811
    version = world["version"]
    holding = threading.Event()
    result = {}

    def submit_slowly():
        try:
            with organization_context(world["org"]), transaction.atomic():
                locked = ProgramVersion.objects.select_for_update(no_key=True).get(pk=version.pk)
                holding.set()
                time.sleep(0.5)
                ProgramVersion.all_organizations.filter(pk=locked.pk).update(status=S.SUBMITTED)
        finally:
            close_old_connections()
            connection.close()

    thread = threading.Thread(target=submit_slowly)
    thread.start()
    assert holding.wait(5)
    response = service().put(
        url(version), {"state": "AA==", "rows": rows_for(world, objective_text="متأخر")}, format="json"
    )
    thread.join()
    result["status"] = response.status_code
    assert result["status"] == 409 and response.json()["error"]["code"] == "version_locked"
    with organization_context(world["org"]):
        assert Block.objects.get(pk=world["objective"].pk).content == doc("هدف")
