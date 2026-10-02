from django.db import migrations

from apps.core.locking import row_lock_trigger_sql

FORWARD, BACKWARD = row_lock_trigger_sql("competencies_competency", "competencies_frameworkversion", "version_id")


class Migration(migrations.Migration):
    dependencies = [("competencies", "0001_initial")]

    operations = [migrations.RunSQL(FORWARD, BACKWARD)]
