from apps.programs.tests.isolation_probes import _version
from apps.suggestions.models import Suggestion
from apps.tenancy.isolation import Probe, register


def _suggestion(org):
    version = _version(org)
    return Suggestion.objects.create(
        version=version,
        kind=Suggestion.Kind.OUTLINE,
        basis_hash="0" * 64,
        request={},
        status=Suggestion.Status.READY,
        requested_by=version.program.owner,
    )


register(Probe(route="version-suggestions", kind="nested", make=_version))
register(Probe(route="suggestion-detail", kind="detail", make=_suggestion))
register(Probe(route="suggestion-accept", kind="action", make=_suggestion))
register(Probe(route="suggestion-dismiss", kind="action", make=_suggestion))
