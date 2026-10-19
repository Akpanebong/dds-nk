from .models import AuditLog
from .access import is_executive_director


def stamp_audit(obj, user, creating=False):
    if not user or not getattr(user, 'is_authenticated', False):
        return obj
    if creating and hasattr(obj, 'created_by'):
        obj.created_by = user
    if hasattr(obj, 'updated_by'):
        obj.updated_by = user
    return obj


def audit(request, action, module, obj=None, detail=''):
    if not getattr(request,'user',None) or not request.user.is_authenticated: return
    AuditLog.objects.create(actor=request.user, created_by=request.user, updated_by=request.user,
        action=action,module=module,
        object_type=obj.__class__.__name__ if obj else '',object_id=obj.slug if obj and getattr(obj,'slug',None) else str(obj.pk) if obj and obj.pk else '',detail=detail)


def recent_audit_activity(user, limit=8):
    """Return dashboard audit activity visible to the current user."""
    queryset = AuditLog.objects.select_related('actor').order_by('-created_at')
    if not is_executive_director(user):
        queryset = queryset.filter(actor=user)
    return queryset[:limit]
