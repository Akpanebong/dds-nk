import uuid

from django.conf import settings
from django.db import models
from django.utils.text import slugify
from hr_app.HRapp.employee_models import Employee


class Appraisal(models.Model):

    APPRAISAL_TYPE_CHOICES = [
        ('mid_year', 'Mid-year'),
        ('annual', 'Annual'),
    ]

    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('sent_to_employee', 'Sent to Employee'),
        ('submitted_by_employee', 'Submitted by Employee'),
        ('reviewed_by_supervisor', 'Reviewed by Supervisor'),
        ('reviewed_by_hr', 'Reviewed by HR'),
        ('approved', 'Approved by CMT'),
    ]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE)
    supervisor = models.ForeignKey(Employee, related_name="supervised_appraisals", on_delete=models.SET_NULL, null=True)
    date_of_submission = models.DateField(null=True, blank=True)
    # === BASIC INFO ===
    appraisal_type = models.CharField(
        max_length=20,
        choices=APPRAISAL_TYPE_CHOICES,
        default='annual',
    )
    year = models.IntegerField(blank=True, null=True)
    duty_station = models.CharField(max_length=200, blank=True)
    years_in_org = models.CharField(max_length=100, blank=True)

    # === SCORES ===
    job_description_score = models.IntegerField(null=True, blank=True)
    job_description_interpretation = models.CharField(max_length=50, blank=True)

    service_score = models.IntegerField(null=True, blank=True)
    service_interpretation = models.CharField(max_length=50, blank=True)

    # === EMPLOYEE INPUT ===
    significant_event = models.TextField(blank=True)
    staff_opinion = models.TextField(blank=True)

    weaknesses = models.TextField(blank=True, null=True)
    strengths = models.TextField(blank=True, null=True)

    capacity_gaps = models.TextField(blank=True, null=True)

    # === SUPERVISOR ===
    supervisor_comment = models.TextField(blank=True, null=True)

    # === HR ===
    hr_comment = models.TextField(blank=True, null=True)

    # === CMT ===
    cmt_comment = models.TextField(blank=True, null=True)
    verdict = models.CharField(max_length=200, blank=True)
    cmt_signature = models.ImageField(upload_to="signatures/", null=True, blank=True)

    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='draft')
    pdf = models.FileField(upload_to="appraisals/", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # appraisal_template = models.FileField(upload_to='appraisals/templates/', null=True, blank=True)
    filled_appraisal = models.FileField(upload_to='appraisals/filled/', null=True, blank=True)
    reference = models.CharField(max_length=20, unique=True, blank=True, editable=False)
    slug = models.SlugField(max_length=80, unique=True, blank=True, editable=False)

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = f"APR-{uuid.uuid4().hex[:6].upper()}"
        if not self.slug:
            self.slug = slugify(f"{self.reference}-{uuid.uuid4().hex[:8]}")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.employee} - {self.year}"


class PerformanceImprovementPlan(models.Model):
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("sent_to_staff", "Sent to Staff"),
        ("submitted_by_staff", "Submitted by Staff"),
        ("reviewed_by_hr", "Reviewed by HR"),
        ("completed", "Completed"),
    ]
    appraisal = models.OneToOneField(Appraisal, on_delete=models.CASCADE, related_name="pip",)
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="pips",)
    token = models.UUIDField(default=uuid.uuid4,unique=True,editable=False,)
    status = models.CharField(max_length=30,choices=STATUS_CHOICES,default="draft",)
    sent_by = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,blank=True,related_name="sent_pips",)
    sent_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    improvement_areas = models.TextField(blank=True,help_text="Areas requiring improvement.")
    improvement_actions = models.TextField(blank=True,help_text="Actions the employee will take.")
    support_required = models.TextField(blank=True,help_text="Support expected from management.")
    expected_completion_date = models.DateField(null=True, blank=True,)
    staff_commitment = models.TextField(blank=True, help_text="Employee's commitment statement.")
    staff_signature = models.ImageField(upload_to="pip/signatures/", null=True,blank=True,)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"PIP | {self.employee} | {self.appraisal.reference}"

    @property
    def is_submitted(self):
        return self.status == "submitted_by_staff"
