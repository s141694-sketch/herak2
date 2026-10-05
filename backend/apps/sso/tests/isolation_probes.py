import itertools

from apps.accounts.models import Role
from apps.programs.tests.factories import member
from apps.sso import services
from apps.sso.models import IdentityProviderConfig
from apps.tenancy.isolation import Probe, register

_n = itertools.count()


def _admin(org):
    return member(f"sso-{org.slug}-{next(_n)}@example.com", Role.ADMIN)


def _domain(org):
    return services.add_domain(f"probe{next(_n)}-{org.slug}.test", actor=_admin(org))


def _provider(org):
    existing = IdentityProviderConfig.objects.first()
    if existing is not None:
        return existing
    return services.save_provider(
        None, actor=_admin(org), issuer=f"https://{org.slug}.idp.test", client_id="harak2", client_secret="probe"
    )


register(Probe(route="sso-domain-list", kind="list", make=_domain))
register(Probe(route="sso-domain-detail", kind="detail", make=_domain))
register(Probe(route="sso-domain-verify", kind="action", make=_domain))
register(Probe(route="sso-provider-list", kind="list", make=_provider))
register(Probe(route="sso-provider-detail", kind="detail", make=_provider))
register(Probe(route="sso-provider-test", kind="action", make=_provider))
register(Probe(route="sso-provider-test-login", kind="action", make=_provider))
register(Probe(route="sso-provider-policy", kind="action", make=_provider))
