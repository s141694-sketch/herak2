from django.apps import AppConfig


class SsoConfig(AppConfig):
    name = "apps.sso"
    label = "sso"
    verbose_name = "Single sign-on"

    def ready(self):
        from apps.tenancy.middleware import ENTRY_CHECKS

        from .enforcement import sso_entry_check

        if sso_entry_check not in ENTRY_CHECKS:
            ENTRY_CHECKS.append(sso_entry_check)
