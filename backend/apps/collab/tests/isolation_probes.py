from apps.programs.tests.isolation_probes import _version
from apps.tenancy.isolation import Probe, register

register(Probe(route="program-version-collab-token", kind="action", make=_version))
