import django.utils.timezone
from django.db import migrations, models


def accepted_when_made(apps, schema_editor):
    """Every membership made before invitations was a member from the start (D90)."""
    Membership = apps.get_model("accounts", "Membership")
    Membership._base_manager.update(accepted_at=models.F("created_at"))


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0005_organization_logo_file"),
    ]

    operations = [
        migrations.AddField(
            model_name="membership",
            name="accepted_at",
            field=models.DateTimeField(
                blank=True, default=django.utils.timezone.now, null=True
            ),
        ),
        migrations.RunPython(accepted_when_made, migrations.RunPython.noop),
    ]
