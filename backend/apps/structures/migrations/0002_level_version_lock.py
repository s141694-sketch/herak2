from django.db import migrations

from apps.core.locking import row_lock_trigger_sql

FORWARD, BACKWARD = row_lock_trigger_sql("structures_level", "structures_templateversion", "version_id")


class Migration(migrations.Migration):
    dependencies = [("structures", "0001_initial")]

    operations = [migrations.RunSQL(FORWARD, BACKWARD)]
