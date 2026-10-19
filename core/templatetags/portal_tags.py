from django import template
register=template.Library()


@register.simple_tag
def active_path(request,path):
    return 'active' if request.path.startswith(path) else ''


@register.filter
def initials(user):
    name=(user.get_full_name() or user.username).strip().split()
    return ''.join(x[0] for x in name[:2]).upper()
