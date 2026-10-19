from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [('meal', '0006_activity_output_strategicobjective_and_more')]

    operations = [migrations.RunSQL(sql=f'DROP TABLE IF EXISTS {table}', reverse_sql=migrations.RunSQL.noop) for table in [
        'monitoring_dataentry', 'monitoring_activityrecord', 'monitoring_indicator',
        'monitoring_activity', 'monitoring_output', 'monitoring_strategicobjective',
        'monitoring_project', 'monitoring_location', 'monitoring_coreprogram',
    ]]
