from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('meal', '0012_quarterplan')]

    operations = [
        migrations.AddField(
            model_name='quarterplan',
            name='reporting_year',
            field=models.PositiveIntegerField(db_index=True, default=2026),
        ),
        migrations.RemoveConstraint(
            model_name='quarterplan',
            name='unique_meal_indicator_quarter_plan',
        ),
        migrations.AddConstraint(
            model_name='quarterplan',
            constraint=models.UniqueConstraint(
                fields=('indicator', 'reporting_year', 'quarter'),
                name='unique_meal_indicator_quarter_plan',
            ),
        ),
        migrations.RemoveIndex(
            model_name='quarterplan',
            name='meal_qplan_quarter_ind_idx',
        ),
        migrations.AddIndex(
            model_name='quarterplan',
            index=models.Index(
                fields=['reporting_year', 'quarter', 'indicator'],
                name='meal_qplan_year_qtr_ind_idx',
            ),
        ),
    ]
