from apps.accounts.models import User
from apps.structures import services
from apps.tenancy.isolation import Probe, register

LEVELS = [{"name_ar": "وحدة", "name_en": "Module"}, {"name_ar": "درس", "name_en": "Lesson"}]


def _template(org):
    actor = User.objects.create_user(email=f"tpl-{org.slug}-{User.objects.count()}@example.com", password="x" * 12)
    return services.create_template(name=f"T {org.slug}", actor=actor, levels=LEVELS)


def _version(org):
    return _template(org).versions.get()


register(Probe(route="structure-template-list", kind="list", make=_template))
register(Probe(route="structure-template-detail", kind="detail", make=_template))
register(Probe(route="structure-template-versions", kind="nested", make=_template))
register(Probe(route="template-version-detail", kind="detail", make=_version))
register(Probe(route="template-version-levels", kind="nested", make=_version))
register(Probe(route="template-version-publish", kind="action", make=_version))
