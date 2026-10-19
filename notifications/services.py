from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.mail import send_mail
from django.db.models import QuerySet
from django.urls import reverse
from django.utils import timezone

from .models import Notification

User = get_user_model()


def _document_url(url):
    """Return a safe internal path, defaulting to the staff workspace."""
    if url and url.startswith('/') and not url.startswith('//'):
        return url
    return reverse('portal')


def _absolute_url(url):
    path = _document_url(url)
    base = getattr(settings, 'APP_BASE_URL', '').rstrip('/')
    return f'{base}{path}' if base else path


def _message_with_link(message, url):
    link = url if url.startswith(('http://', 'https://')) else _document_url(url)
    if link in message or _absolute_url(link) in message:
        return message
    return f'{message}\n\nOpen document: {link}'


def notify_user(user, title, message, *, level='info', url='', email=False):
    """Create a linked in-app notification and optionally send a linked email."""
    if not user or not getattr(user, 'is_active', True):
        return None
    target = _document_url(url)
    linked_message = _message_with_link(message, target)
    item = Notification.objects.create(recipient=user, title=title, message=linked_message, level=level, url=target)
    if email and user.email:
        send_mail(title, _message_with_link(message, _absolute_url(target)), None, [user.email], fail_silently=True)
    return item


def notify_users(users, title, message, **kwargs):
    """Notify a queryset, manager, or iterable of users."""
    if isinstance(users, QuerySet):
        users = users.filter(is_active=True)
    return [notify_user(user, title, message, **kwargs) for user in users]


def notify_group(group_name, title, message, **kwargs):
    users = User.objects.filter(groups__name=group_name, is_active=True).distinct()
    return notify_users(users, title, message, **kwargs)


def mark_read(notification):
    notification.read_at = timezone.now()
    notification.save(update_fields=['read_at'])
    return notification
