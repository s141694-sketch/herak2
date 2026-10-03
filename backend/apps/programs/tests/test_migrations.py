"""Migrations must run over existing data, not only on an empty database."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from apps.accounts.models import Organization, Role
from apps.programs import services
from apps.programs.tests.factories import member, program
from apps.tenancy.context import organization_context

BEFORE_LINK_KEYS = ("programs", "0006_alignmentlink_version_lock")


def migrate(targets):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)


@pytest.mark.django_db(transaction=True)
def test_link_keys_are_backfilled_one_per_existing_link():
    org = Organization.objects.create(name="A", slug="a")
    with organization_context(org):
        owner = member("author@example.com", Role.AUTHOR)
        prog = program(owner)
        version = prog.versions.get()
        node = services.add_node(version, title="ن", actor=owner)
        objective = services.add_block(version, node=node, type="objective", actor=owner)
        for competency in version.framework_version.competencies.all()[:2]:
            services.link(version, kind="objective_competency", source=objective, actor=owner, competency=competency)
    try:
        migrate([BEFORE_LINK_KEYS])
        migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())
    finally:
        migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())
    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*), COUNT(DISTINCT link_key), COUNT(link_key) FROM programs_alignmentlink")
        assert cursor.fetchone() == (2, 2, 2)
