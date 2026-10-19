from uuid import uuid4

from django.utils.text import slugify


def unique_slug(instance, value):
    """Return a readable slug that is unique for the model's table."""
    base = slugify(value)[:220] or f'{instance.__class__.__name__.lower()}-{uuid4().hex[:8]}'
    candidate = base
    suffix = 2
    queryset = instance.__class__.objects.all()
    if instance.pk:
        queryset = queryset.exclude(pk=instance.pk)
    while queryset.filter(slug=candidate).exists():
        candidate = f'{base}-{suffix}'
        suffix += 1
    return candidate
