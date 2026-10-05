from django.apps import AppConfig


class SsoConfig(AppConfig):
    name = "apps.sso"
    label = "sso"
    verbose_name = "Single sign-on"

    def ready(self):
        from apps.tenancy.middleware import ENTRY_CHECKS

        from .enforcement import sso_entry_check, sso_scope_entry_check

        # First: when an organization asks for its provider, that is what the person is told, whatever else
        # (a second factor) the session also lacks.
        for position, check in enumerate((sso_entry_check, sso_scope_entry_check)):
            if check not in ENTRY_CHECKS:
                ENTRY_CHECKS.insert(position, check)
