from django.db import migrations


def add_base_groups(apps, schema_editor):
    StaffProfile = apps.get_model("core", "StaffProfile")
    Group = apps.get_model("auth", "Group")
    type_names = {"Staff", "Volunteer", "Intern", "VSLA"}

    for profile in StaffProfile.objects.all().select_related("department"):
        type_group, _ = Group.objects.get_or_create(
            name=profile.user_type if profile.user_type in type_names else "Staff"
        )
        profile.groups.add(type_group)
        if profile.department_id:
            department_group, _ = Group.objects.get_or_create(
                name=profile.department.name
            )
            profile.groups.add(department_group)


class Migration(migrations.Migration):
    dependencies = [("core", "0014_normalize_staff_groups")]

    operations = [migrations.RunPython(add_base_groups, migrations.RunPython.noop)]
