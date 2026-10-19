from django.utils import timezone

from .access import user_can_manage, user_has_access
from notifications.models import Notification


def portal_context(request):
    profile = request.user if request.user.is_authenticated else None
    user = request.user
    is_superuser = bool(user.is_authenticated and user.is_superuser)
    group_names = set(user.groups.values_list('name', flat=True)) if user.is_authenticated else set()
    is_ed = is_superuser or bool(group_names.intersection({'ED', 'Executive Director'}))
    is_hr = is_superuser or is_ed or bool(group_names.intersection({'HR', 'Human Resources'}))
    is_department_head = bool(
        user.is_authenticated
        and (
            is_superuser
            or (
                user.department_id
                and user.department.head_id == user.pk
            )
        )
    )
    notifications = Notification.objects.filter(recipient=request.user)[:8] if request.user.is_authenticated else Notification.objects.none()
    unread_notifications = Notification.objects.filter(recipient=request.user, read_at__isnull=True) if request.user.is_authenticated else Notification.objects.none()
    return {
        'staff_profile': profile,
        'module_access': {
            'meal': user_has_access(request.user, 'meal'),
            'procurement': user_has_access(request.user, 'procurement'),
            'hr': user_has_access(request.user, 'hr'),
            'vsla': user_has_access(request.user, 'vsla'),
        } if request.user.is_authenticated else {},
        'manage_access': {
            'meal': user_can_manage(request.user, 'meal'),
            'procurement': user_can_manage(request.user, 'procurement'),
            'hr': user_can_manage(request.user, 'hr'),
        } if request.user.is_authenticated else {},
        'can_view_probation_register': is_hr,
        'can_view_ed_probation_review': is_ed,
        'can_view_department_sessions': is_department_head,
        'portal_name': 'DDS-NK THRIVE Integrated Management System',
        'now': timezone.now(),
        'notifications': notifications,
        'unread_notification_count': unread_notifications.count(),
    }
