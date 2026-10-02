from apps.accounts.models import Role
from apps.tenancy.isolation import Probe, register

from .factories import member, program


def _program(org):
    from apps.accounts.models import User

    owner = member(f"prog-{org.slug}-{User.objects.count()}@example.com", Role.AUTHOR)
    return program(owner)


def _version(org):
    return _program(org).versions.get()


def _collaborator(org):
    return _program(org).collaborators.get()


register(Probe(route="program-list", kind="list", make=_program))
register(Probe(route="program-detail", kind="detail", make=_program))
register(Probe(route="program-collaborators", kind="nested", make=_program))
register(Probe(route="program-collaborator-detail", kind="detail", make=_collaborator))
register(Probe(route="program-versions", kind="nested", make=_program))
register(Probe(route="program-version-detail", kind="detail", make=_version))
register(Probe(route="program-version-targets", kind="nested", make=_version))
register(Probe(route="program-version-submit", kind="action", make=_version))
register(Probe(route="program-version-withdraw", kind="action", make=_version))


def _node(org):
    from apps.programs import services

    version = _version(org)
    return services.add_node(version, title="n", actor=version.created_by)


def _block(org):
    from apps.programs import services

    node = _node(org)
    return services.add_block(node.version, node=node, type="content", actor=node.version.created_by)


register(Probe(route="program-version-tree", kind="nested", make=_version))
register(Probe(route="program-version-nodes", kind="nested", make=_version))
register(Probe(route="program-version-blocks", kind="nested", make=_version))
register(Probe(route="program-node-detail", kind="detail", make=_node))
register(Probe(route="program-node-move", kind="action", make=_node))
register(Probe(route="program-node-restore", kind="action", make=_node))
register(Probe(route="program-block-detail", kind="detail", make=_block))
register(Probe(route="program-block-restore", kind="action", make=_block))


def _link(org):
    from apps.programs import services
    from apps.programs.models import AlignmentLink

    block = _block(org)
    services.update_block(block, type="objective", actor=block.version.created_by)
    competency = block.version.framework_version.competencies.first()
    return services.link(
        block.version,
        kind=AlignmentLink.Kind.OBJECTIVE_COMPETENCY,
        source=block,
        competency=competency,
        actor=block.version.created_by,
    )


register(Probe(route="program-version-links", kind="nested", make=_version))
register(Probe(route="alignment-link-detail", kind="detail", make=_link))

register(
    Probe(
        route="program-version-diff",
        kind="nested",
        make=_version,
        url_kwargs=lambda version: {"pk": version.pk, "other": version.pk},
    )
)
