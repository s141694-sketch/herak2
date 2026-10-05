from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = "apps.accounts"
    label = "accounts"

    def ready(self):
        from apps.tenancy.middleware import ENTRY_CHECKS

        from .mfa import mfa_entry_check

        if mfa_entry_check not in ENTRY_CHECKS:
            ENTRY_CHECKS.append(mfa_entry_check)
