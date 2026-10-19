from django import template
register = template.Library()


@register.filter
def has_group(user, group_name):
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    if getattr(user, 'is_superuser', False):
        return True
    return user.groups.filter(name=group_name).exists()
