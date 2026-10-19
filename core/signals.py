from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.contrib.auth.models import Group
from .models import Department, StaffProfile

@receiver(post_save, sender=StaffProfile)
def sync_profile_groups(sender, instance, **kwargs):
    from .access import sync_access_groups, sync_department_group, sync_user_type_group
    sync_access_groups(instance)
    sync_department_group(instance)
    sync_user_type_group(instance)

    supervisor_group, _ = Group.objects.get_or_create(name='Supervisor')
    # ``supervised_by`` belongs to the staff member being edited, but the
    # Supervisor role belongs to the selected supervisor.
    supervisor = instance.supervised_by
    if supervisor:
        supervisor.groups.add(supervisor_group)

    previous_supervisor_id = getattr(instance, '_previous_supervisor_id', None)
    if previous_supervisor_id and previous_supervisor_id != instance.supervised_by_id:
        previous_supervisor = sender.objects.filter(pk=previous_supervisor_id).first()
        if previous_supervisor and not previous_supervisor.supervised_staff.exists() and not previous_supervisor.is_superuser:
            previous_supervisor.groups.remove(supervisor_group)


@receiver(pre_save, sender=StaffProfile)
def remember_previous_department(sender, instance, **kwargs):
    """Capture the persisted department before a staff edit is saved."""
    if not instance.pk:
        instance._previous_department_id = None
        return
    instance._previous_department_id = sender.objects.filter(
        pk=instance.pk,
    ).values_list('department_id', flat=True).first()
    instance._previous_supervisor_id = sender.objects.filter(
        pk=instance.pk,
    ).values_list('supervised_by_id', flat=True).first()


@receiver(post_save, sender=Department)
def sync_department_head_groups(sender, instance, **kwargs):
    from .access import sync_access_groups
    for user in StaffProfile.objects.all():
        sync_access_groups(user)
