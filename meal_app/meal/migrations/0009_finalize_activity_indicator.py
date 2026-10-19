from django.db import migrations, models
import django.db.models.deletion


def remove_legacy_indicators(apps, schema_editor):
    Indicator = apps.get_model('meal', 'Indicator')
    Indicator.objects.filter(output__isnull=True, title__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [('meal', '0008_merge_activity_into_indicator')]
    operations = [
        migrations.RunPython(remove_legacy_indicators, migrations.RunPython.noop),
        migrations.AlterField(model_name='indicator', name='title', field=models.CharField(max_length=500, verbose_name='Activity')),
        migrations.AlterField(model_name='indicator', name='created_at', field=models.DateTimeField(auto_now_add=True)),
        migrations.AlterField(model_name='activityrecord', name='indicator', field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='records', to='meal.indicator')),
    ]
