from django.db import migrations

from apps.core.locking import row_lock_trigger_sql

NODE_FORWARD, NODE_BACKWARD = row_lock_trigger_sql("programs_node", "programs_programversion", "version_id")
BLOCK_FORWARD, BLOCK_BACKWARD = row_lock_trigger_sql("programs_block", "programs_programversion", "version_id")


class Migration(migrations.Migration):
    dependencies = [("programs", "0003_node_block_node_programs_node_key_unique_and_more")]

    operations = [migrations.RunSQL(NODE_FORWARD, NODE_BACKWARD), migrations.RunSQL(BLOCK_FORWARD, BLOCK_BACKWARD)]
