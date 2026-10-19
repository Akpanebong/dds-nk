from django.core.exceptions import ValidationError
from django.utils import timezone

from core.models import StaffProfile as Profile
from core.models import Department
from django.db import models


class OrientationPlanStatus(models.TextChoices):
    IN_PROGRESS = "in_progress", "In progress"
    COMPLETED = "completed", "Completed"
    CANCELED = "canceled", "Canceled"


class OrientationSessionStatus(models.TextChoices):
    AWAITING_SCHEDULE = "awaiting_schedule", "Awaiting schedule"
    SCHEDULED = "scheduled", "Scheduled"
    COMPLETED = "completed", "Completed"
    CANCELED = "canceled", "Canceled"


class OrientationPlan(models.Model):
    staff = models.OneToOneField(Profile, on_delete=models.CASCADE, related_name="orientation_plan",
                                 limit_choices_to=models.Q(is_active=True),)
    created_by = models.ForeignKey(Profile, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="created_orientation_plans",)
    status = models.CharField(max_length=16, choices=OrientationPlanStatus.choices,
                              default=OrientationPlanStatus.IN_PROGRESS, db_index=True,)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "id"]

    def __str__(self):
        return f"OrientationPlan({self.staff})"

    @property
    def completion_percent(self) -> int:
        total = self.sessions.exclude(status=OrientationSessionStatus.CANCELED).count()
        if total == 0:
            return 0
        done = self.sessions.filter(status=OrientationSessionStatus.COMPLETED).count()
        return int(round((done / total) * 100))

    def refresh_status_from_sessions(self):
        if self.status == OrientationPlanStatus.CANCELED:
            return
        total = self.sessions.exclude(status=OrientationSessionStatus.CANCELED).count()
        done = self.sessions.filter(status=OrientationSessionStatus.COMPLETED).count()
        if total > 0 and done == total:
            self.status = OrientationPlanStatus.COMPLETED
        else:
            self.status = OrientationPlanStatus.IN_PROGRESS
        self.save(update_fields=["status", "updated_at"])


class OrientationSession(models.Model):
    plan = models.ForeignKey(
        OrientationPlan, on_delete=models.CASCADE, related_name="sessions"
    )
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="orientation_sessions")

    status = models.CharField(max_length=20, choices=OrientationSessionStatus.choices,
                              default=OrientationSessionStatus.AWAITING_SCHEDULE, db_index=True,)
    requested_at = models.DateTimeField(auto_now_add=True)
    scheduled_start = models.DateTimeField(null=True, blank=True, db_index=True)
    scheduled_end = models.DateTimeField(null=True, blank=True, db_index=True)
    scheduled_by = models.ForeignKey(Profile, on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name="scheduled_orientation_sessions",)
    completed_at = models.DateTimeField(null=True, blank=True)
    completion_notes = models.TextField(blank=True)

    class Meta:
        unique_together = (("plan", "department"),)
        ordering = ["-requested_at", "id"]

    def __str__(self):
        return f"{self.plan.staff} | {self.department}"

    @property
    def staff(self) -> Profile:
        return self.plan.staff

    @property
    def department_head(self) -> Profile:
        return self.department.head

    def clean(self):
        super().clean()

        if (self.scheduled_start is None) ^ (self.scheduled_end is None):
            raise ValidationError("Both start and end time are required.")

        if self.scheduled_start and self.scheduled_end and self.scheduled_end <= self.scheduled_start:
            raise ValidationError("End time must be after start time.")

        if not (self.scheduled_start and self.scheduled_end):
            return

        # Prevent schedule overlaps for the same staff between departments.
        qs = OrientationSession.objects.filter(plan=self.plan).exclude(pk=self.pk)
        qs = qs.exclude(status=OrientationSessionStatus.CANCELED)
        overlaps = qs.filter(
            scheduled_start__lt=self.scheduled_end,
            scheduled_end__gt=self.scheduled_start,
        )
        if overlaps.exists():
            raise ValidationError(
                "This orientation time conflicts with another department orientation for this staff."
            )

    def mark_scheduled(self, *, start, end, by_user: Profile):
        self.scheduled_start = start
        self.scheduled_end = end
        self.scheduled_by = by_user
        self.status = OrientationSessionStatus.SCHEDULED
        self.full_clean()
        self.save()

    def mark_completed(self, *, by_user: Profile, notes: str = ""):
        self.status = OrientationSessionStatus.COMPLETED
        self.completed_at = timezone.now()
        self.completion_notes = notes or ""
        self.full_clean()
        self.save()
