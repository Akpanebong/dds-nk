from django.db import migrations, models
import django.db.models.deletion


def map_units_to_departments(apps, schema_editor):
    Unit = apps.get_model("HRapp", "Unit")
    Department = apps.get_model("core", "Department")
    Session = apps.get_model("HRapp", "OrientationSession")
    departments = {department.name: department.pk for department in Department.objects.all()}

    for session in Session.objects.select_related("unit").all():
        department_id = departments.get(session.unit.name)
        if department_id:
            session.unit_id = department_id
            session.save(update_fields=["unit"])
        else:
            session.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("HRapp", "0002_alter_orientationplan_staff"),
        ("core", "0011_staffprofile_signature"),
    ]

    operations = [
        migrations.RunPython(map_units_to_departments, migrations.RunPython.noop),
        migrations.RenameField(
            model_name="orientationsession",
            old_name="unit",
            new_name="department",
        ),
        migrations.AlterField(
            model_name="orientationsession",
            name="department",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="orientation_sessions",
                to="core.department",
            ),
        ),
        migrations.AlterUniqueTogether(
            name="orientationsession",
            unique_together={("plan", "department")},
        ),
        migrations.DeleteModel(name="ForumPost"),
        migrations.DeleteModel(name="ForumThread"),
        migrations.DeleteModel(name="Supervisor"),
        migrations.DeleteModel(name="Unit"),
    ]
