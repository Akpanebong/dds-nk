from django.db import migrations, models
from django.utils.text import slugify


def fill_slugs(apps, schema_editor):
    for model_name, source in (
        ('Indicator', lambda obj: obj.code or obj.name),
        ('DataCollection', lambda obj: f'{obj.title}-{obj.reporting_period}'),
        ('Report', lambda obj: f'{obj.title}-{obj.period}'),
    ):
        model = apps.get_model('meal', model_name)
        for obj in model.objects.order_by('pk'):
            base = slugify(source(obj))[:220] or f'{model_name.lower()}-{obj.pk}'
            slug, number = base, 2
            while model.objects.filter(slug=slug).exclude(pk=obj.pk).exists():
                slug = f'{base}-{number}'
                number += 1
            model.objects.filter(pk=obj.pk).update(slug=slug)


class Migration(migrations.Migration):
    dependencies = [('meal', '0002_alter_datacollection_options')]
    operations = [
        migrations.AddField(model_name='indicator', name='slug', field=models.SlugField(max_length=255, null=True)),
        migrations.AddField(model_name='datacollection', name='slug', field=models.SlugField(max_length=255, null=True)),
        migrations.AddField(model_name='report', name='slug', field=models.SlugField(max_length=255, null=True)),
        migrations.RunPython(fill_slugs, migrations.RunPython.noop),
        migrations.AlterField(model_name='indicator', name='slug', field=models.SlugField(max_length=255, unique=True)),
        migrations.AlterField(model_name='datacollection', name='slug', field=models.SlugField(max_length=255, unique=True)),
        migrations.AlterField(model_name='report', name='slug', field=models.SlugField(max_length=255, unique=True)),
    ]
