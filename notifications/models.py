from django.conf import settings
from django.db import models
from core.models import AuditStampedModel


class Notification(AuditStampedModel):
    LEVELS = [('info', 'Information'), ('success', 'Success'), ('warning', 'Warning'), ('error', 'Error')]
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications')
    title = models.CharField(max_length=160)
    message = models.TextField()
    level = models.CharField(max_length=20, choices=LEVELS, default='info')
    url = models.CharField(max_length=500, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['recipient', 'read_at', '-created_at'])]

    @property
    def is_read(self):
        return self.read_at is not None
