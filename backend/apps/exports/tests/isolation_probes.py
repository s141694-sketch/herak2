from apps.programs.tests.isolation_probes import _version
from apps.tenancy.isolation import Probe, register

register(Probe(route="version-export", kind="action", make=_version))
register(Probe(route="version-export-retry", kind="action", make=_version))
