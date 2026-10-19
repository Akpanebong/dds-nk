from decimal import Decimal

from django.db import migrations, models
import django.db.models.deletion


def backfill_supplier_spend_lines(apps, schema_editor):
    Report = apps.get_model('procurement', 'SupplierSpendReport')
    PurchaseOrder = apps.get_model('procurement', 'PurchaseOrder')
    for report in list(Report.objects.select_related('purchase_order', 'supplier', 'requisition')):
        po = report.purchase_order
        if not po:
            continue
        items = list(po.requisition.items.all())
        if not items:
            report.report_year = po.issue_date.year
            report.awarded_amount = po.final_amount or Decimal('0.00')
            report.grand_total = po.final_amount or Decimal('0.00')
            report.total_spent = po.final_amount or Decimal('0.00')
            report.save(update_fields=['report_year', 'awarded_amount', 'grand_total', 'total_spent'])
            continue
        invoice_values = {
            'invoice_no': report.invoice_no,
            'invoice_date': report.invoice_date,
            'invoice_amount': report.invoice_amount,
            'payment_status': report.payment_status,
        }
        report.delete()
        for item in items:
            product_id = None
            if item.procurement_item_id:
                product_id = item.procurement_item.product_id
            Report.objects.create(
                supplier=po.supplier,
                product_id=product_id,
                requisition_item_id=item.pk,
                report_year=po.issue_date.year,
                qty=item.qty or Decimal('0.00'),
                awarded_amount=po.final_amount or Decimal('0.00'),
                line_total=(item.qty or Decimal('0.00')) * (item.unit_price or Decimal('0.00')),
                grand_total=po.final_amount or Decimal('0.00'),
                total_spent=po.final_amount or Decimal('0.00'),
                purchase_order=po,
                requisition=po.requisition,
                **invoice_values,
            )


class Migration(migrations.Migration):
    dependencies = [('procurement', '0015_direct_purchase_purchase_order_links')]

    operations = [
        migrations.RemoveConstraint(
            model_name='supplierspendreport',
            name='unique_supplier_spend_report_per_purchase_order',
        ),
        migrations.AddField(model_name='supplierspendreport', name='product', field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='supplier_spend_reports', to='procurement.product')),
        migrations.AddField(model_name='supplierspendreport', name='requisition_item', field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='supplier_spend_reports', to='procurement.requisitionitem')),
        migrations.AddField(model_name='supplierspendreport', name='report_year', field=models.PositiveIntegerField(blank=True, db_index=True, null=True)),
        migrations.AddField(model_name='supplierspendreport', name='qty', field=models.DecimalField(decimal_places=2, default=0, max_digits=10)),
        migrations.AddField(model_name='supplierspendreport', name='awarded_amount', field=models.DecimalField(decimal_places=2, default=0, max_digits=18)),
        migrations.AddField(model_name='supplierspendreport', name='line_total', field=models.DecimalField(decimal_places=2, default=0, max_digits=18)),
        migrations.AddField(model_name='supplierspendreport', name='grand_total', field=models.DecimalField(decimal_places=2, default=0, max_digits=18)),
        migrations.RunPython(backfill_supplier_spend_lines, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='supplierspendreport',
            constraint=models.UniqueConstraint(fields=('purchase_order', 'requisition_item'), name='unique_supplier_spend_report_per_order_item'),
        ),
    ]
