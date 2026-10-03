from apps.programs import services as program_services
from apps.programs.tests.isolation_probes import _program
from apps.quality import services
from apps.quality.models import Finding
from apps.tenancy.isolation import Probe, register


def _version_with_report(org):
    program = _program(org)
    version = program.versions.get()
    program_services.add_node(version, title="n", actor=program.owner)
    report = services.request_run(version, "full")
    services.execute_run(report.pk, str(report.run_id))
    return version


def _finding(org):
    return Finding.objects.filter(report__version=_version_with_report(org)).first()


register(Probe(route="version-quality", kind="detail", make=_version_with_report))
register(Probe(route="version-quality-run", kind="action", make=_version_with_report))
register(Probe(route="finding-dismiss", kind="action", make=_finding))
register(Probe(route="finding-restore", kind="action", make=_finding))
