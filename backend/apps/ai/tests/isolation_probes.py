from apps.tenancy.isolation import Probe, register

register(Probe(route="ai-policy", kind="current"))
