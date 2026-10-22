from django.contrib.auth.models import Group
from functools import wraps
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.contrib import messages


ACCESS_GROUPS = {
    'meal': 'MEAL',
    'procurement': 'Procurement',
    'hr': 'HR',
}

USER_TYPE_GROUPS = {
    'Staff': 'Staff',
    'Volunteer': 'Volunteer',
    'Intern': 'Intern',
    'VSLA': 'VSLA',
}

HEAD_GROUPS = {
    'meal': 'MEAL Head',
    'procurement': 'Procurement Head',
    'hr': 'HR Head',
}


def sync_access_groups(user):
    """Synchronize role-specific head groups only.

    Module groups are not default staff memberships.  Access to modules is
    controlled by the access helpers and explicit role groups are managed by
    HR/admin assignment.
    """
    if not getattr(user, 'pk', None):
        return
    for access_name, head_group_name in HEAD_GROUPS.items():
        head_group, _ = Group.objects.get_or_create(name=head_group_name)
        is_head = user.is_superuser or user.department_id and user.department.key == access_name and user.department.head_id == user.pk
        if is_head:
            user.groups.add(head_group)
        else:
            user.groups.remove(head_group)


def sync_department_group(user):
    """Keep a staff member in exactly their current Department group.

    Department groups use the Department name so they remain understandable
    to administrators. Empty groups are intentionally retained for reuse.
    """
    if not getattr(user, 'pk', None):
        return

    from .models import Department

    current_department = getattr(user, 'department', None)
    previous_department_id = getattr(user, '_previous_department_id', None)

    if previous_department_id and previous_department_id != getattr(user, 'department_id', None):
        previous_department = Department.objects.filter(pk=previous_department_id).first()
        if previous_department:
            old_group = Group.objects.filter(name=previous_department.name).first()
            if old_group:
                user.groups.remove(old_group)

    if current_department:
        department_group, _ = Group.objects.get_or_create(name=current_department.name)
        user.groups.add(department_group)


def sync_user_type_group(user):
    """Keep exactly the current user-type group for a staff profile."""
    if not getattr(user, 'pk', None):
        return

    current_name = USER_TYPE_GROUPS.get(getattr(user, 'user_type', 'Staff'), 'Staff')
    for group_name in USER_TYPE_GROUPS.values():
        group, _ = Group.objects.get_or_create(name=group_name)
        if group_name == current_name:
            user.groups.add(group)
        else:
            user.groups.remove(group)


def user_has_access(user, access_name):
    """Return read/navigation access for any authenticated staff member.

    Department membership remains relevant to ``user_can_manage`` and to
    workflow-specific actions.  Read access is intentionally global because
    staff may need to inspect and download records owned by another unit.
    """
    if not getattr(user, 'is_authenticated', False):
        return False
    if getattr(user, 'user_type', 'Staff') == 'VSLA':
        return access_name == 'vsla'
    return True


def user_can_manage(user, access_name):
    if not getattr(user, 'is_authenticated', False):
        return False
    if is_executive_director(user) or (
        user.department_id
        and user.department.key == access_name
        and user.department.head_id == user.pk
    ):
        return True
    group_name = HEAD_GROUPS.get(access_name)
    return bool(group_name and user.groups.filter(name=group_name).exists())


def is_executive_director(user):
    """Central role rule for ED/superuser full system access."""
    if not getattr(user, 'is_authenticated', False):
        return False
    if user.is_superuser:
        return True
    title = (getattr(user, 'job_title', '') or '').strip().lower()
    return title in {'ed', 'executive director', 'executive director (ed)'} or user.groups.filter(name__in=['ED', 'Executive Director']).exists()


def access_required(module, *, manage=False):
    """Reusable view decorator for module access and CRUD/review authorization."""
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(request, *args, **kwargs):
            allowed = user_can_manage(request.user, module) if manage else user_has_access(request.user, module)
            return view(request, *args, **kwargs) if allowed else redirect('portal')
        return wrapped
    return decorator


def crud_access_required(module):
    return access_required(module, manage=True)


def read_access_required(module):
    """Explicit alias for module pages and file/download endpoints."""
    return access_required(module, manage=False)


def download_access_required(module):
    """Explicit alias for downloadable records shared across departments."""
    return access_required(module, manage=False)


def has_staff_signature(user):
    """Return whether a staff member has uploaded a usable signature file."""
    if not getattr(user, 'is_authenticated', False):
        return False
    signature = getattr(user, 'signature', None)
    return bool(signature and getattr(signature, 'name', ''))


def signature_required(view):
    """Reusable guard for actions that create or submit signed documents.

    The redirect target is deliberately the self-service profile, making this
    suitable for procurement, requisitions, leave, and future workflows.
    """
    @wraps(view)
    @login_required
    def wrapped(request, *args, **kwargs):
        if not has_staff_signature(request.user):
            messages.warning(request, 'Upload your staff signature before creating or submitting this document.')
            return redirect('hr:profile')
        return view(request, *args, **kwargs)
    return wrapped


def signer_conflict(document, user, fields=None):
    """Return True when ``user`` has already signed another stage."""
    if not getattr(user, 'is_authenticated', False):
        return True
    fields = fields or ('created_by', 'reviewed_by', 'checked_by', 'approved_by', 'rejected_by')
    return any(getattr(document, f'{field}_id', None) == user.pk for field in fields)


def ensure_separation_of_duty(document, user, fields=None):
    """Raise a validation error if an actor would sign twice on a document."""
    from django.core.exceptions import ValidationError
    if signer_conflict(document, user, fields=fields):
        raise ValidationError('Separation of duty violation: this staff member has already signed this document.')
