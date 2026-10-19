from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils import timezone
from core.models import AuditStampedModel


# ============================================================================
# CHOICES
# ============================================================================

ACTIVITY_TYPES = (
    ("people", "People activity"),
    ("non_people", "Non-people activity"),
)

ACTIVITY_STATUSES = (
    ("pending", "Pending"),
    ("in_progress", "In progress"),
    ("completed", "Completed"),
    ("on_hold", "On hold"),
)

QUARTER_CHOICES = (
    ("Q1", "Q1"),
    ("Q2", "Q2"),
    ("Q3", "Q3"),
    ("Q4", "Q4"),
)


def current_reporting_year():
    return timezone.localdate().year


# ============================================================================
# STRATEGIC OBJECTIVE
# ============================================================================

class StrategicObjective(AuditStampedModel):
    code = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
    )

    title = models.CharField(
        max_length=400,
    )

    description = models.TextField(
        blank=True,
    )

    class Meta:
        ordering = ["code"]
        verbose_name = "Strategic Objective"
        verbose_name_plural = "Strategic Objectives"

    def __str__(self):
        return f"{self.code} - {self.title}"


# ============================================================================
# OUTPUT
# ============================================================================

class Output(AuditStampedModel):
    objective = models.ForeignKey(StrategicObjective, related_name="outputs", on_delete=models.CASCADE,)
    code = models.CharField(max_length=50, unique=True, db_index=True,)
    title = models.CharField(max_length=400,)
    description = models.TextField(blank=True,)

    class Meta:
        ordering = ["code"]
        verbose_name = "Output"
        verbose_name_plural = "Outputs"
        indexes = [
            models.Index(
                fields=["objective", "code"],
                name="meal_output_obj_code_idx",
            ),
        ]

    def __str__(self):
        return f"{self.code} - {self.title}"


# ============================================================================
# INDICATOR / ACTIVITY
# ============================================================================
#
# DDS-NK currently treats an Indicator as the reporting/activity entity.
# The compatibility property `activity` is retained so existing templates
# and views can continue using r.activity.
# ============================================================================

class Indicator(AuditStampedModel):
    activity_type = models.CharField(max_length=20, choices=ACTIVITY_TYPES, default="people", db_index=True,)
    code = models.CharField(max_length=50, unique=True, db_index=True,)
    title = models.CharField(max_length=500, verbose_name="Activity",)
    output = models.ForeignKey(Output, related_name="indicators", on_delete=models.PROTECT, null=True, blank=True,)
    indicator_text = models.CharField(max_length=500, blank=True, verbose_name="Indicator",)
    indicator_type = models.CharField(max_length=50, blank=True,)
    numerator = models.CharField(max_length=300, blank=True,)
    denominator = models.CharField(max_length=300, blank=True,)
    baseline = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)],)
    target = models.DecimalField(max_digits=14, decimal_places=2, null=True,
                                 blank=True, validators=[MinValueValidator(0)],)
    quarter = models.CharField(max_length=2, choices=QUARTER_CHOICES, blank=True,)
    unit = models.CharField(max_length=100, blank=True,)
    data_source = models.CharField(max_length=300, blank=True,)
    reporting_frequency = models.CharField(max_length=80, blank=True,)
    responsible = models.CharField(max_length=250, blank=True,)
    notes = models.TextField(blank=True,)
    active = models.BooleanField(default=True, db_index=True,)
    class Meta:
        ordering = ["code"]

        verbose_name = "Activity"
        verbose_name_plural = "Activities"

        indexes = [
            models.Index(
                fields=["active", "activity_type"],
                name="meal_ind_active_type_idx",
            ),
            models.Index(
                fields=["output", "active"],
                name="meal_ind_output_active_idx",
            ),
        ]

    @property
    def is_people(self):
        return self.activity_type == "people"

    @property
    def activity(self):
        """
        Backward-compatible alias.

        Existing code can continue to use:
            record.activity
        """
        return self

    def __str__(self):
        return f"{self.code} - {self.title}"


# ============================================================================
# WORKBOOK QUARTER PLAN
# ============================================================================

class QuarterPlan(AuditStampedModel):

    indicator = models.ForeignKey(Indicator, related_name="quarter_plans", on_delete=models.CASCADE,)
    reporting_year = models.PositiveIntegerField(default=2026, db_index=True)
    quarter = models.CharField(max_length=2, choices=QUARTER_CHOICES)
    target = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    planned_budget = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    budget_expense = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    workbook_result = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    source_row = models.PositiveIntegerField(null=True, blank=True)
    class Meta:
        ordering = ["indicator__code"]
        constraints = [
            models.UniqueConstraint(
                fields=["indicator", "reporting_year", "quarter"],
                name="unique_meal_indicator_quarter_plan",
            )
        ]
        indexes = [
            models.Index(fields=["reporting_year", "quarter", "indicator"], name="meal_qplan_year_qtr_ind_idx"),
        ]

    def __str__(self):
        return f"{self.indicator.code} | {self.quarter}"


# ============================================================================
# ACTIVITY RECORD
# ============================================================================

class ActivityRecord(AuditStampedModel):

    indicator = models.ForeignKey(
        Indicator,
        related_name="records",
        on_delete=models.PROTECT,
    )

    reporting_year = models.PositiveIntegerField(
        default=current_reporting_year,
        db_index=True,
    )

    reporting_month = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[
            MinValueValidator(1),
            MaxValueValidator(12),
        ],
        help_text="Leave blank for an annual record.",
    )

    status = models.CharField(
        max_length=20,
        choices=ACTIVITY_STATUSES,
        default="pending",
        db_index=True,
    )

    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="meal_activity_records",
    )

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_meal_activity_records",
    )

    reviewed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    # ------------------------------------------------------------------------
    # PEOPLE DISAGGREGATION
    # ------------------------------------------------------------------------

    women = models.PositiveIntegerField(
        default=0,
    )

    men = models.PositiveIntegerField(
        default=0,
    )

    male_youth = models.PositiveIntegerField(
        default=0,
    )

    female_youth = models.PositiveIntegerField(
        default=0,
    )

    boys = models.PositiveIntegerField(
        default=0,
    )

    girls = models.PositiveIntegerField(
        default=0,
    )

    pwd_male = models.PositiveIntegerField(
        default=0,
    )

    pwd_female = models.PositiveIntegerField(
        default=0,
    )

    progress_value = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )

    comments = models.TextField(
        blank=True,
    )

    class Meta:
        ordering = [
            "-reporting_year",
            "-reporting_month",
            "-created_at",
        ]

        indexes = [
            models.Index(
                fields=[
                    "reporting_year",
                    "reporting_month",
                ],
                name="meal_record_period_idx",
            ),
            models.Index(
                fields=[
                    "reporting_year",
                    "status",
                ],
                name="meal_record_year_status_idx",
            ),
            models.Index(
                fields=[
                    "indicator",
                    "reporting_year",
                ],
                name="meal_record_ind_year_idx",
            ),
        ]

        constraints = [

            # Monthly records must be unique.
            models.UniqueConstraint(
                fields=[
                    "indicator",
                    "reporting_year",
                    "reporting_month",
                ],
                condition=models.Q(reporting_month__isnull=False),
                name="unique_meal_indicator_month",
            ),

            # Annual record must be unique.
            models.UniqueConstraint(
                fields=[
                    "indicator",
                    "reporting_year",
                ],
                condition=models.Q(reporting_month__isnull=True),
                name="unique_meal_indicator_year",
            ),
        ]

    # ------------------------------------------------------------------------
    # COMPATIBILITY
    # ------------------------------------------------------------------------

    @property
    def activity(self):
        return self.indicator

    # ------------------------------------------------------------------------
    # PEOPLE METRICS
    # ------------------------------------------------------------------------

    @property
    def total_people(self):
        return (
            self.women
            + self.men
            + self.male_youth
            + self.female_youth
            + self.boys
            + self.girls
        )

    @property
    def total_youth(self):
        return self.male_youth + self.female_youth

    @property
    def total_children(self):
        return self.boys + self.girls

    @property
    def total_pwd(self):
        return self.pwd_male + self.pwd_female

    # ------------------------------------------------------------------------
    # DISPLAY HELPERS
    # ------------------------------------------------------------------------

    @property
    def reporting_period(self):
        if self.reporting_month:
            return f"{self.reporting_year}-{self.reporting_month:02d}"

        return str(self.reporting_year)

    @property
    def cumulative_progress(self):
        """
        NOTE:
        This property performs a query.

        For dashboards and bulk reports, calculate cumulative progress
        using queryset aggregation instead of repeatedly accessing this
        property.
        """
        return (
            self.indicator.records
            .filter(
                reporting_year=self.reporting_year,
            )
            .aggregate(
                total=models.Sum("progress_value"),
            )
            ["total"]
            or 0
        )

    @property
    def progress_percent(self):
        target = self.indicator.target

        if not target:
            return 0

        return round(
            float(self.cumulative_progress)
            / float(target)
            * 100,
            1,
        )

    def __str__(self):
        return f"{self.indicator.code} | {self.reporting_period}"
