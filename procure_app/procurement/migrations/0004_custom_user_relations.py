from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('core', '0004_staffprofile_custom_user'), ('procurement', '0003_add_slugs')]
    operations = [
        migrations.AlterField(
            model_name='procurementrequest',
            name='requested_by',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL),
        ),
    ]
