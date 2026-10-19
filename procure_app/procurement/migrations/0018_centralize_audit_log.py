import json

from django.db import migrations


def move_procurement_audit_logs(apps, schema_editor):
    OldAuditLog = apps.get_model('procurement', 'AuditLog')
    AuditLog = apps.get_model('core', 'AuditLog')
    for entry in OldAuditLog.objects.all().iterator():
        detail = json.dumps(entry.meta, default=str) if entry.meta else ''
        AuditLog.objects.create(
            slug=f'procurement-audit-{entry.pk}',
            actor_id=entry.user_id,
            created_by_id=entry.user_id,
            updated_by_id=entry.user_id,
            action=entry.action,
            module='Procurement',
            detail=detail,
            created_at=entry.timestamp,
        )


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0011_staffprofile_signature'),
        ('procurement', '0017_rfqsendlog_response_status'),
    ]

    operations = [
        migrations.RunPython(move_procurement_audit_logs, migrations.RunPython.noop),
        migrations.DeleteModel(name='AuditLog'),
    ]
