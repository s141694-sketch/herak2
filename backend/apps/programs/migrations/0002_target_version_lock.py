from django.db import migrations

from apps.core.locking import row_lock_trigger_sql

FORWARD, BACKWARD = row_lock_trigger_sql("programs_programtarget", "programs_programversion", "version_id")


class Migration(migrations.Migration):
    dependencies = [("programs", "0001_initial")]

    operations = [migrations.RunSQL(FORWARD, BACKWARD)]
