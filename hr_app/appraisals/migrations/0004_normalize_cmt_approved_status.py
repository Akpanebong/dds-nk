from django.db import migrations


def normalize_approved_status(apps, schema_editor):
    Appraisal = apps.get_model("appraisals", "Appraisal")
    Appraisal.objects.filter(status="approved_by_cmt").update(status="approved")


class Migration(migrations.Migration):

    dependencies = [
        ("appraisals", "0003_appraisal_appraisal_type"),
    ]

    operations = [
        migrations.RunPython(normalize_approved_status, migrations.RunPython.noop),
    ]
