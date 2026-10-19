from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('procurement', '0016_supplier_spend_report_lines')]

    operations = [
        migrations.AddField(
            model_name='rfqsendlog',
            name='responded',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='rfqsendlog',
            name='responded_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
