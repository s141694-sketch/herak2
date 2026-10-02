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
