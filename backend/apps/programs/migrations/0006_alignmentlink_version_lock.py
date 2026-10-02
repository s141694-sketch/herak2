from django.db import migrations

from apps.core.locking import row_lock_trigger_sql

FORWARD, BACKWARD = row_lock_trigger_sql("programs_alignmentlink", "programs_programversion", "version_id")


class Migration(migrations.Migration):
    dependencies = [("programs", "0005_alignmentlink")]

    operations = [migrations.RunSQL(FORWARD, BACKWARD)]
