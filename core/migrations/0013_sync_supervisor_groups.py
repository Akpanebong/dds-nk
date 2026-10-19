from django.db import migrations


def add_supervisor_groups(apps, schema_editor):
    StaffProfile = apps.get_model("core", "StaffProfile")
    Group = apps.get_model("auth", "Group")
    supervisor_group, _ = Group.objects.get_or_create(name="Supervisor")

    supervisors = StaffProfile.objects.filter(
        supervised_staff__isnull=False,
    ).distinct()
    for supervisor in supervisors.iterator():
        supervisor.groups.add(supervisor_group)


class Migration(migrations.Migration):
    dependencies = [("core", "0012_remove_staffprofile_hr_access_and_more")]

    operations = [migrations.RunPython(add_supervisor_groups, migrations.RunPython.noop)]
