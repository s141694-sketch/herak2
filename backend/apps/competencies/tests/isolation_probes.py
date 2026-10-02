from apps.accounts.models import User
from apps.competencies import services
from apps.tenancy.isolation import Probe, register


def _actor(org):
    return User.objects.create_user(email=f"fw-{org.slug}-{User.objects.count()}@example.com", password="x" * 12)


def _framework(org):
    return services.create_framework(name=f"F {org.slug}", actor=_actor(org))


def _version(org):
    version = _framework(org).versions.get()
    services.add_competency(version, code="C-1", title="t")
    return version


def _competency(org):
    return _version(org).competencies.get()


register(Probe(route="competency-framework-list", kind="list", make=_framework))
register(Probe(route="competency-framework-detail", kind="detail", make=_framework))
register(Probe(route="competency-framework-versions", kind="nested", make=_framework))
register(Probe(route="framework-version-detail", kind="detail", make=_version))
register(Probe(route="framework-version-publish", kind="action", make=_version))
register(Probe(route="framework-version-competencies", kind="nested", make=_version))
register(Probe(route="competency-detail", kind="detail", make=_competency))
