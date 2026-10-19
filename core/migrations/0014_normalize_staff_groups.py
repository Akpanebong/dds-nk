from django.db import migrations


def normalize_staff_groups(apps, schema_editor):
    StaffProfile = apps.get_model("core", "StaffProfile")
    Group = apps.get_model("auth", "Group")

    module_groups = list(
        Group.objects.filter(name__in=["MEAL", "Procurement", "HR"])
    )
    if not module_groups:
        return

    protected_role_names = {
        "Supervisor",
        "Reviewer",
        "ED",
        "Executive Director",
        "HR Head",
        "MEAL Head",
        "Procurement Head",
        "Human Resources",
    }

    for profile in StaffProfile.objects.all().select_related("department"):
        is_department_head = bool(
            profile.department_id
            and profile.department.head_id == profile.pk
        )
        is_supervisor = profile.supervised_staff.exists()
        has_role_group = profile.groups.filter(
            name__in=protected_role_names,
        ).exists()

        # Keep HR membership for HR-department staff, but remove the other
        # blanket module memberships. Ordinary staff lose all three.
        keep_hr = bool(
            profile.department_id
            and (profile.department.key or "").lower() == "hr"
        )
        if not (profile.is_superuser or is_department_head or is_supervisor or has_role_group or keep_hr):
            profile.groups.remove(*module_groups)
        else:
            removable = [group for group in module_groups if group.name != "HR" or not keep_hr]
            if removable:
                profile.groups.remove(*removable)


class Migration(migrations.Migration):
    dependencies = [("core", "0013_sync_supervisor_groups")]

    operations = [migrations.RunPython(normalize_staff_groups, migrations.RunPython.noop)]
