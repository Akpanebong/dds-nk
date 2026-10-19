import uuid
from django.contrib.auth.models import Group
from django.core.validators import MinValueValidator
from django.db import models
from dateutil.relativedelta import relativedelta
from decimal import Decimal

from core.model_audit_stamp import AuditStampedModel
from core.slug import unique_slug
from django.db.models import F, Q
from django.utils import timezone


# Kept for historical migration deconstruction. The related document models
# are no longer part of the active DDS-NK project workflow.
def project_document_upload_to(instance, filename):
    return f"projects/{instance.project_id}/{getattr(instance, 'document_type', 'documents')}/{filename}"


def project_submission_upload_to(instance, filename):
    return f"projects/{instance.project_id}/submissions/{getattr(instance, 'document_type', 'document')}/{filename}"


def activity_concept_note_upload_to(instance, filename):
    return f"projects/{instance.activity_id}/concept-notes/{filename}"


class Project(AuditStampedModel):
    STATUS_CHOICES = (
        ('planning', 'Planning'), ('active', 'Active'), ('on_hold', 'On hold'),
        ('completed', 'Completed'), ('closed', 'Closed'),
    )
    code = models.CharField(max_length=50, unique=True, blank=True, db_index=True)
    projected_reach = models.PositiveIntegerField(default=0)
    name = models.CharField(max_length=120, unique=True)
    donor = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='planning', db_index=True)
    project_head = models.ForeignKey('core.StaffProfile', on_delete=models.SET_NULL, null=True, blank=True, related_name="project_head_projects")
    project_accountant = models.ForeignKey('core.StaffProfile', on_delete=models.SET_NULL, null=True, blank=True, related_name="accountant_projects")
    project_officer = models.ForeignKey('core.StaffProfile', on_delete=models.SET_NULL, null=True, blank=True, related_name="officer_projects")
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    duration_days = models.CharField(max_length=300, null=True, blank=True)
    location = models.TextField(null=True, blank=True)
    slug = models.SlugField(null=True, blank=True, editable=False, unique=True)

    class Meta:
        ordering = ("name",)
        constraints = [
            models.CheckConstraint(
                condition=Q(start_date__isnull=True) | Q(end_date__isnull=True) | Q(end_date__gte=F('start_date')),
                name='project_dates_are_ordered',
            ),
        ]

    @property
    def duration(self):
        if not self.start_date or not self.end_date:
            return ""
        months = (self.end_date.year - self.start_date.year) * 12 + self.end_date.month - self.start_date.month
        if self.end_date.day < self.start_date.day:
            months -= 1
        years, remaining_months = divmod(max(months, 0), 12)
        return f"{years} years, {remaining_months} months"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(self, self.name)
        if not self.code:
            self.code = f"DDS-{uuid.uuid4().hex[:6].upper()}"
        if self.start_date and self.end_date:
            rd = relativedelta(self.end_date, self.start_date)
            self.duration_days = f"{rd.years}y {rd.months}m {rd.days}d"
        else:
            self.duration_days = None

        super().save(*args, **kwargs)

        for person in [self.project_head, self.project_accountant, self.project_officer]:
            if person:
                group, _ = Group.objects.get_or_create(name=self.name)
                person.groups.add(group)

    def __str__(self):
        return f"{self.code} — {self.name}"


class ProjectBudget(AuditStampedModel):
    FULL_YEAR = "FULL_YEAR"
    Q1 = "Q1"
    Q2 = "Q2"
    Q3 = "Q3"
    Q4 = "Q4"

    PERIOD_CHOICES = (
        (FULL_YEAR, "Full Year"),
        (Q1, "Quarter 1"),
        (Q2, "Quarter 2"),
        (Q3, "Quarter 3"),
        (Q4, "Quarter 4"),
    )

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="budgets")
    fiscal_year = models.CharField(max_length=128)
    period = models.CharField(max_length=20, choices=PERIOD_CHOICES, default=FULL_YEAR)
    budget_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )
    class Meta:
        ordering = ("-fiscal_year", "period")
        unique_together = ("project", "fiscal_year", "period")
        indexes = [models.Index(fields=["project", "fiscal_year", "period"])]

    def __str__(self):
        return f"{self.project} - {self.fiscal_year} - {self.get_period_display()}"

    @property
    def quarterly_remainder(self):
        """Annual amount less the four quarterly allocations for this year."""
        if self.period != self.FULL_YEAR:
            return Decimal("0.00")
        quarter_total = self.project.budgets.filter(
            fiscal_year=self.fiscal_year,
            period__in=[self.Q1, self.Q2, self.Q3, self.Q4],
        ).exclude(pk=self.pk).aggregate(total=models.Sum("budget_amount"))["total"] or Decimal("0.00")
        return self.budget_amount - quarter_total

    @classmethod
    def current_fiscal_year(cls):
        return str(timezone.now().date().year)
