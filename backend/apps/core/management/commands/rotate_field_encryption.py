"""Encrypts every stored secret again with the first of FIELD_ENCRYPTION_KEYS (D64), so an older key can then be
removed from the setting: TOTP secrets and identity providers' client secrets."""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import TOTPDevice
from apps.core import secrets
from apps.sso.models import IdentityProviderConfig


class Command(BaseCommand):
    help = "Re-encrypt stored secrets with the first FIELD_ENCRYPTION_KEYS key."

    @transaction.atomic
    def handle(self, *args, **options):
        devices = TOTPDevice.objects.select_for_update()
        for device in devices:
            device.secret_encrypted = secrets.rotate(device.secret_encrypted)
            device.save(update_fields=["secret_encrypted"])
        providers = IdentityProviderConfig.all_organizations.select_for_update().exclude(client_secret_encrypted="")
        for config in providers:
            IdentityProviderConfig.all_organizations.filter(pk=config.pk).update(
                client_secret_encrypted=secrets.rotate(config.client_secret_encrypted)
            )
        self.stdout.write(f"re-encrypted {len(devices)} second factors and {len(providers)} client secrets")
