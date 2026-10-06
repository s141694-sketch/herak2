import itertools

from apps.accounts.models import Role
from apps.files import services
from apps.files.models import File
from apps.programs.tests.factories import member
from apps.tenancy.isolation import Probe, register

_n = itertools.count()


def _file(org):
    actor = member(f"files-{org.slug}-{next(_n)}@example.com", Role.ADMIN)
    return services.store(
        b"probe", name="probe.docx", content_type="application/octet-stream", kind=File.Kind.EXPORT, actor=actor
    )


register(Probe(route="file-download", kind="action", make=_file))
