from django.conf import settings
from django.db import models
from django.utils import timezone


class AuditStampedModel(models.Model):
    """Reusable audit metadata for application records."""

    created_at = models.DateTimeField(default=timezone.now, db_index=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey( settings.AUTH_USER_MODEL, null=True, blank=True, editable=False, on_delete=models.SET_NULL, related_name="created_%(class)ss",)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, editable=False, on_delete=models.SET_NULL, related_name="updated_%(class)ss",)

    class Meta:
        abstract = True


class ApprovalStatus(models.TextChoices):
    PENDING = "Pending", "Pending"
    REVIEWED = "Reviewed", "Reviewed"
    CHECKED = "Checked", "Checked"
    APPROVED = "Approved", "Approved"
    REJECTED = "Rejected", "Rejected"


class ApprovalWorkflowModel(AuditStampedModel):
    status = models.CharField(max_length=20, choices=ApprovalStatus.choices, default=ApprovalStatus.PENDING)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL,null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="%(class)s_reviewed")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    checked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="%(class)s_checked")
    checked_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="%(class)s_approved")
    approved_at = models.DateTimeField(null=True, blank=True)

    rejected_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="%(class)s_rejected")
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)

    class Meta:
        abstract = True

    @property
    def is_approved(self):
        return self.status == ApprovalStatus.APPROVED

