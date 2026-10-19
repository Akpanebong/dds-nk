import datetime
import uuid
from django.conf import settings
from django.db import models
import hashlib
from django.db.models import F, Q, Sum
from django.utils.text import slugify
from django.core.exceptions import ValidationError
from core.models import StaffProfile
from .employee_models import Employee

Profile = StaffProfile
from collections import defaultdict


STATUS = [('Active', 'Active'), ('On Leave', 'On Leave'), ('Exit', 'Exit')]


class Attendance(models.Model):
    employee = models.ForeignKey(Profile, on_delete=models.SET_NULL, null=True, blank=True)
    date = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=10, default='Absent',
        choices=[('Present', 'Present'), ('Absent', 'Absent'), ('Leave', 'Leave')]
    )
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    address = models.CharField(max_length=255, null=True, blank=True)

    def __str__(self):
        return f"{self.employee} - {self.date}"


class LeaveType(models.Model):
    name = models.CharField(max_length=50, default="Annual")
    no_of_days = models.PositiveIntegerField(blank=True, null=True, default=21)
    is_special = models.BooleanField(default=False)

    @property
    def is_without_pay(self) -> bool:
        normalized = (self.name or "").strip().lower()
        compact = "".join(ch for ch in normalized if ch.isalnum())
        # tolerate common data-entry variants/misspellings (e.g. "Withuot Pay")
        return compact in {"withoutpay", "withuotpay", "wihtoutpay"} or "withoutpay" in compact

    def __str__(self):
        return self.name


class SpecialLeaveType(models.Model):
    name = models.CharField(max_length=50, default="Compassionate")  # Sick, Compassionate

    def __str__(self):
        return self.name


class Leave(models.Model):
    STATUS_CHOICES = [
        ("Pending", "Pending"),
        ("SupervisorApproved", "Supervisor Approved"),
        ("HRApproved", "HR Approved"),
        ("Approved", "Approved"),
        ("Denied", "Denied"),
    ]

    employee = models.ForeignKey(Profile, on_delete=models.SET_NULL, null=True, blank=True, related_name="leaves")
    # leave_type = models.CharField(max_length=32, choices=LEAVE_TYPES, default="Annual")
    leave_type = models.ForeignKey(LeaveType, on_delete=models.CASCADE)
    special_type = models.ForeignKey(SpecialLeaveType, on_delete=models.CASCADE, null=True, blank=True)
    start_date = models.DateField()
    end_date = models.DateField()
    working_days = models.PositiveSmallIntegerField(default=0, db_index=True, editable=False)
    reason = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    applied_date = models.DateTimeField(auto_now_add=True)

    supervisor = models.ForeignKey(Employee, null=True, blank=True, on_delete=models.SET_NULL)
    hr = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                           related_name="hr_approvals")
    ed = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                           related_name="ed_approvals")

    supervisor_approved = models.BooleanField(default=False)
    supervisor_approved_at = models.DateTimeField(null=True, blank=True)
    hr_approved = models.BooleanField(default=False)
    hr_approved_at = models.DateTimeField(null=True, blank=True)
    ed_approved = models.BooleanField(default=False)
    ed_approved_at = models.DateTimeField(null=True, blank=True)
    slug = models.SlugField(null=True, blank=True, unique=True, editable=False)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default="Pending")

    class Meta:
        indexes = [
            models.Index(fields=["employee", "leave_type", "status", "start_date"]),
            models.Index(fields=["status", "start_date"]),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(start_date__lte=models.F("end_date")),
                name="leave_start_date_before_end_date",
            ),
        ]

    def __str__(self):
        return f"{self.employee} | {self.leave_type} | {self.start_date} → {self.end_date}"

    @staticmethod
    def compute_working_days(start_date, end_date) -> int:
        if not start_date or not end_date or end_date < start_date:
            return 0

        total_days = (end_date - start_date).days + 1  # inclusive
        full_weeks, remainder = divmod(total_days, 7)
        working = full_weeks * 5

        start_weekday = start_date.weekday()  # 0=Mon .. 6=Sun
        for i in range(remainder):
            if (start_weekday + i) % 7 < 5:
                working += 1
        return working

    # ✅ WORKING DAYS (correct)
    @property
    def days_requested(self):
        if self.working_days:
            return int(self.working_days)
        return self.compute_working_days(self.start_date, self.end_date)

    @staticmethod
    def _year_bounds(year: int):
        year = int(year)
        return datetime.date(year, 1, 1), datetime.date(year, 12, 31)

    @classmethod
    def _overlap_working_days(cls, *, start_date, end_date, period_start, period_end) -> int:
        if not start_date or not end_date or end_date < start_date:
            return 0
        if end_date < period_start or start_date > period_end:
            return 0
        effective_start = max(start_date, period_start)
        effective_end = min(end_date, period_end)
        return int(cls.compute_working_days(effective_start, effective_end) or 0)

    @classmethod
    def entitled_days(cls, *, leave_type) -> int:
        return int(getattr(leave_type, "no_of_days", 0) or 0)

    @classmethod
    def used_days(cls, *, employee, year: int, leave_type, statuses=None, exclude_pk=None) -> int:
        """
        Days already used/held within the year for this leave type.

        Only fully approved requests count as used leave. Pending and partially
        approved requests do not reduce the employee's used balance.
        """
        if statuses is None:
            statuses = ["Approved"]

        year_start, year_end = cls._year_bounds(year)
        qs = cls.objects.filter(
            employee=employee,
            leave_type=leave_type,
            status__in=statuses,
            start_date__lte=year_end,
            end_date__gte=year_start,
        ).only("id", "start_date", "end_date", "working_days")

        if exclude_pk:
            qs = qs.exclude(pk=exclude_pk)

        total = 0
        for leave in qs:
            total += cls._overlap_working_days(
                start_date=leave.start_date,
                end_date=leave.end_date,
                period_start=year_start,
                period_end=year_end,
            )
        return int(total or 0)

    @classmethod
    def remaining_days(cls, *, employee, year, leave_type):
        entitled = cls.entitled_days(leave_type=leave_type)
        used = cls.used_days(employee=employee, year=int(year), leave_type=leave_type)
        return max(0, int(entitled) - int(used))

    # ✅ STATUS LOGIC (cleaned)
    def update_status(self):
        if self.supervisor_approved and self.hr_approved and self.ed_approved:
            self.status = "Approved"
        elif self.supervisor_approved and self.hr_approved:
            self.status = "HRApproved"
        elif self.supervisor_approved:
            self.status = "SupervisorApproved"
        else:
            self.status = "Pending"

    @classmethod
    def yearly_staff_summary(cls, year):

        rows = (
            cls.objects.filter(status="Approved", start_date__year=year)
            .values("employee")
            .annotate(total_days=Sum("working_days"))
            .order_by("-total_days")
        )

        profiles = Profile.objects.in_bulk([r["employee"] for r in rows])
        return [
            {"employee": profiles.get(r["employee"]), "total_days": int(r["total_days"] or 0)}
            for r in rows
            if profiles.get(r["employee"]) is not None
        ]

    @classmethod
    def yearly_staff_summary_for_leave_type(cls, *, year: int, leave_type, include_zero: bool = True):
        """
        Yearly approved leave totals per staff for a specific leave type.

        If include_zero=True, returns rows for all eligible staff (profile_type='Staff',
        excluding Exit/Suspended) with 0 days where none were approved.
        """
        from django.db.models import Sum
        from core.models import StaffProfile as Profile

        approved_rows = {
            row["employee"]: int(row["total_days"] or 0)
            for row in (
                cls.objects.filter(status="Approved", start_date__year=year, leave_type=leave_type)
                .values("employee")
                .annotate(total_days=Sum("working_days"))
            )
        }

        if not include_zero:
            profiles = Profile.objects.in_bulk(list(approved_rows.keys()))
            return [
                {"employee": profiles.get(emp_id), "total_days": total_days}
                for emp_id, total_days in approved_rows.items()
                if profiles.get(emp_id) is not None
            ]

        eligible_staff = (
            Profile.objects.filter(is_active=True)
            .order_by("last_name", "first_name", "username")
        )
        return [
            {"employee": staff, "total_days": approved_rows.get(staff.id, 0)}
            for staff in eligible_staff
        ]

    @classmethod
    def yearly_total_days(cls, year):
        from django.db.models import Sum
        return int(
            cls.objects.filter(status="Approved", start_date__year=year)
            .aggregate(total=Sum("working_days"))
            .get("total")
            or 0
        )

    @classmethod
    def approved_days(cls, *, employee, year, leave_type):
        from django.db.models import Sum

        return int(
            cls.objects.filter(
                employee=employee,
                leave_type=leave_type,
                status="Approved",
                start_date__year=year
            ).aggregate(total=Sum("working_days"))["total"] or 0
        )

    @classmethod
    def yearly_leave_allocation_vs_used(cls, *, year, leave_type):
        """
        Aggregates approved leave-days vs allotted leave-days for the year.

        Allotted is computed as: eligible_staff_count * leave_type.no_of_days
        """
        from django.db.models import Sum
        from core.models import StaffProfile as Profile

        staff_qs = Profile.objects.filter(is_active=True)
        staff_count = staff_qs.count()
        allotted_per_staff = int(getattr(leave_type, "no_of_days", 0) or 0)
        allotted_total_days = staff_count * allotted_per_staff

        approved_total_days = int(
            cls.objects.filter(status="Approved", start_date__year=year, leave_type=leave_type)
            .aggregate(total=Sum("working_days"))
            .get("total")
            or 0
        )

        return {
            "year": int(year),
            "leave_type": leave_type,
            "staff_count": staff_count,
            "allotted_per_staff": allotted_per_staff,
            "allotted_total_days": allotted_total_days,
            "approved_total_days": approved_total_days,
            "remaining_total_days": max(0, allotted_total_days - approved_total_days),
        }

    def clean(self):

        # Ensure special_type only applies to Special leave
        if self.leave_type.is_special and not self.special_type:
            raise ValidationError("Special leave requires a subtype (Sick or Compassionate).")

        if not self.leave_type.is_special:
            self.special_type = None

        # Reason only required for Special
        if self.leave_type.is_special and not self.reason:
            raise ValidationError("Reason is required for Special leave.")

        if self.end_date < self.start_date:
            raise ValidationError("End date cannot be before start date.")

        # Special leave has no fixed allocation; its duration is agreed between
        # the supervisor and the employee. All other leave types must remain
        # within the employee's yearly allocation, including this request.
        if not (self.employee_id and self.leave_type_id and self.start_date and self.end_date):
            return

        if self.leave_type.is_special:
            return

        entitled = self.entitled_days(leave_type=self.leave_type)
        if entitled <= 0:
            raise ValidationError(
                f"{self.leave_type} leave is not allocated (0 days). Contact HR."
            )

        start_year = int(self.start_date.year)
        end_year = int(self.end_date.year)
        for year in range(start_year, end_year + 1):
            year_start, year_end = self._year_bounds(year)
            requested_in_year = self._overlap_working_days(
                start_date=self.start_date,
                end_date=self.end_date,
                period_start=year_start,
                period_end=year_end,
            )
            if requested_in_year <= 0:
                continue

            already_used = self.used_days(
                employee=self.employee,
                year=year,
                leave_type=self.leave_type,
                exclude_pk=self.pk,
            )
            remaining = entitled - already_used
            if requested_in_year > remaining:
                raise ValidationError(
                    f"Requested {requested_in_year} days exceeds the {remaining} "
                    f"remaining {self.leave_type} leave days for {year}."
                )

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = uuid.uuid4().hex[:40]
        # cache computed working days for fast summaries
        if self.start_date and self.end_date:
            self.working_days = self.compute_working_days(self.start_date, self.end_date)
        super().save(*args, **kwargs)


class LeaveSchedule(models.Model):
    STATUS_CHOICES = (("Planned", "Planned"), ("Reviewed", "Reviewed"), ("Cancelled", "Cancelled"))

    employee = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="leave_schedules")
    year = models.PositiveIntegerField()
    leave_type = models.ForeignKey(LeaveType, on_delete=models.SET_NULL, null=True, blank=True)
    start_date = models.DateField()
    end_date = models.DateField()
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Planned")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("year", "start_date", "employee__last_name")

    def clean(self):
        if self.end_date < self.start_date:
            raise ValidationError("End date cannot be before start date.")
        if self.start_date.year != self.year or self.end_date.year != self.year:
            raise ValidationError("Both leave dates must fall within the selected plan year.")

    def __str__(self):
        return f"{self.employee} | {self.year} | {self.start_date} → {self.end_date}"


class LeaveDocument(models.Model):
    leave = models.ForeignKey('Leave', on_delete=models.CASCADE, related_name='documents')
    file = models.FileField(upload_to='leave_documents/')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Document for {self.leave} - {self.created_at.strftime('%Y-%m-%d')}"


# Training Module
class Training(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField()
    start_date = models.DateField()
    end_date = models.DateField()
    participants = models.ManyToManyField(Profile, blank=True, limit_choices_to=~models.Q(department__name="ED"))
    slug = models.SlugField(null=True, blank=True, unique=True, editable=False)

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.title)
            self.slug = f"{base_slug}-{uuid.uuid4().hex[:10]}"
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title


class SituationReport(models.Model):
    STATUS_CHOICES = [
        ("Pending", "⏳ Pending"),
        ("Reviewed", "👁 Reviewed"),
        ("Resolved", "✅ Resolved"),
    ]

    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sitrep_reports")
    title = models.CharField(max_length=255)
    description = models.TextField()
    attachment = models.FileField(upload_to="sitreps/", null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Pending")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.title} ({self.status})"


class StaffDevice(models.Model):
    staff = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="devices")
    device_hash = models.CharField(max_length=255, unique=True)
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField()
    approved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.staff.user.get_full_name()} - {self.device_hash[:10]}... ({'Approved' if self.approved else 'Pending'})"

    @staticmethod
    def generate_hash(ip, user_agent):
        return hashlib.sha256(f"{ip}_{user_agent}".encode("utf-8")).hexdigest()
