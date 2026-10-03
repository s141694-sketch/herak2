from apps.comments import services
from apps.programs import services as program_services
from apps.programs.tests.isolation_probes import _program
from apps.tenancy.isolation import Probe, register


def _comment(org):
    program = _program(org)
    version = program.versions.get()
    node = program_services.add_node(version, title="n", actor=program.owner)
    return services.create_comment(
        program=program, version=version, author=program.owner, body="b", category="suggestion", node_key=node.node_key
    )


register(Probe(route="program-comments", kind="nested", make=_program))
register(Probe(route="comment-detail", kind="detail", make=_comment))
register(Probe(route="comment-replies", kind="nested", make=_comment))
register(Probe(route="comment-resolve", kind="action", make=_comment))
register(Probe(route="comment-reopen", kind="action", make=_comment))
