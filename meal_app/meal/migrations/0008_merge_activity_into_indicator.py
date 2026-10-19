from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def merge_activity_rows(apps, schema_editor):
    Activity = apps.get_model('meal', 'Activity')
    Indicator = apps.get_model('meal', 'Indicator')
    ActivityRecord = apps.get_model('meal', 'ActivityRecord')
    for activity in Activity.objects.all():
        indicator = Indicator.objects.filter(code=activity.code).first()
        if indicator is None:
            indicator = Indicator(code=activity.code, name=activity.title)
        indicator.title = activity.title
        indicator.output_id = activity.output_id
        indicator.activity_type = activity.activity_type
        indicator.indicator_text = activity.indicator_text
        indicator.indicator_type = activity.indicator_type
        indicator.numerator = activity.numerator
        indicator.denominator = activity.denominator
        indicator.baseline = activity.baseline
        indicator.target = activity.target or 0
        indicator.data_source = activity.data_source
        indicator.reporting_frequency = activity.reporting_frequency
        indicator.responsible = activity.responsible
        indicator.notes = activity.notes
        indicator.active = activity.active
        indicator.save()
        ActivityRecord.objects.filter(activity_id=activity.pk).update(indicator_id=indicator.pk)


class Migration(migrations.Migration):
    dependencies = [('meal', '0007_remove_legacy_monitoring_tables'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.AddField(model_name='indicator', name='activity_type', field=models.CharField(choices=[('people', 'People activity'), ('non_people', 'Non-people activity')], db_index=True, default='people', max_length=20)),
        migrations.AddField(model_name='indicator', name='created_at', field=models.DateTimeField(auto_now_add=True, blank=True, null=True)),
        migrations.AddField(model_name='indicator', name='indicator_text', field=models.CharField(blank=True, max_length=500, verbose_name='Indicator')),
        migrations.AddField(model_name='indicator', name='output', field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='indicators', to='meal.output')),
        migrations.AddField(model_name='indicator', name='title', field=models.CharField(blank=True, max_length=500, null=True, verbose_name='Activity')),
        migrations.AddField(model_name='activityrecord', name='indicator', field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='records', to='meal.indicator')),
        migrations.RunPython(merge_activity_rows, migrations.RunPython.noop),
        migrations.RemoveConstraint(model_name='activityrecord', name='unique_meal_activity_period'),
        migrations.RemoveField(model_name='activity', name='output'),
        migrations.RemoveField(model_name='indicator', name='activity'),
        migrations.RemoveField(model_name='activityrecord', name='activity'),
        migrations.RemoveField(model_name='indicator', name='name'),
        migrations.AlterModelOptions(name='indicator', options={'ordering': ['code'], 'verbose_name': 'Activity', 'verbose_name_plural': 'Activities'}),
        migrations.AddConstraint(model_name='activityrecord', constraint=models.UniqueConstraint(fields=('indicator', 'reporting_year', 'reporting_month'), name='unique_meal_indicator_period')),
        migrations.DeleteModel(name='Activity'),
    ]
