from django.db import migrations, models
from django.utils.text import slugify
import uuid


def populate_appraisal_slugs(apps, schema_editor):
    Appraisal = apps.get_model("appraisals", "Appraisal")
    for appraisal in Appraisal.objects.filter(slug__isnull=True) | Appraisal.objects.filter(slug=""):
        appraisal.slug = slugify(f"{appraisal.reference}-{uuid.uuid4().hex[:8]}")
        appraisal.save(update_fields=["slug"])


class Migration(migrations.Migration):
    dependencies = [("appraisals", "0004_normalize_cmt_approved_status")]
    operations = [
        migrations.AddField(
            model_name="appraisal",
            name="slug",
            field=models.SlugField(blank=True, editable=False, max_length=80, null=True, unique=True),
        ),
        migrations.RunPython(populate_appraisal_slugs, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="appraisal",
            name="slug",
            field=models.SlugField(blank=True, editable=False, max_length=80, unique=True),
        ),
    ]
