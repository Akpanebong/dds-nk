from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('procurement', '0014_alter_procurementplanitem_delivery_date'),
    ]

    operations = [
        migrations.AlterField(
            model_name='purchaseorder',
            name='send_log',
            field=models.ForeignKey(blank=True, null=True, on_delete=models.SET_NULL, related_name='purchase_orders', to='procurement.rfqsendlog'),
        ),
        migrations.AlterField(
            model_name='purchaseorder',
            name='rfq',
            field=models.ForeignKey(blank=True, null=True, on_delete=models.SET_NULL, related_name='purchase_orders', to='procurement.rfq'),
        ),
    ]
