from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models, transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.text import slugify
from uuid import uuid4


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class VSLAGroup(TimeStampedModel):
    class Status(models.TextChoices):
        FORMING = "forming", "Forming"
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"
        CLOSED = "closed", "Closed"

    name = models.CharField(max_length=180)
    code = models.CharField(max_length=30, unique=True, blank=True)
    slug = models.SlugField(max_length=200, unique=True, blank=True)
    project_name = models.CharField(max_length=180, blank=True)
    donor_name = models.CharField(max_length=180, blank=True)
    district = models.CharField(max_length=100, blank=True)
    sub_county = models.CharField(max_length=100, blank=True)
    parish_or_village = models.CharField(max_length=160, blank=True)
    meeting_day = models.CharField(max_length=20, blank=True)
    meeting_location = models.CharField(max_length=200, blank=True)
    weekly_share_value = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("5000"), validators=[MinValueValidator(Decimal("0.01"))])
    max_shares_per_week = models.PositiveSmallIntegerField(default=5, validators=[MinValueValidator(1), MaxValueValidator(20)])
    loan_interest_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("5.00"), validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))], help_text="Percentage per loan cycle; configure this to match the group's constitution.")
    loan_duration_weeks = models.PositiveSmallIntegerField(default=12, validators=[MinValueValidator(1), MaxValueValidator(104)])
    start_date = models.DateField(default=timezone.localdate)
    cycle_end_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.FORMING)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="vsla_groups_created")

    class Meta:
        ordering = ["name"]
        permissions = [("access_vsla", "Can access VSLA management module"), ("approve_vsla_loan", "Can approve VSLA loans"), ("post_vsla_transactions", "Can post VSLA financial transactions")]
        indexes = [models.Index(fields=["status", "district"]), models.Index(fields=["project_name", "donor_name"])]

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = f"VSLA-{timezone.localdate():%y%m}-{uuid4().hex[:6].upper()}"
        if not self.slug:
            base = slugify(self.name) or "vsla-group"
            self.slug = f"{base}-{uuid4().hex[:6]}"
        super().save(*args, **kwargs)

    @property
    def active_member_count(self):
        return self.members.filter(status=VSLAMember.Status.ACTIVE).count()

    @property
    def total_savings(self):
        return self.savings_transactions.filter(status=LedgerEntry.Status.POSTED, transaction_type=SavingsTransaction.Type.DEPOSIT).aggregate(v=Sum("amount"))["v"] or Decimal("0")

    def __str__(self):
        return f"{self.name} ({self.code})"


class VSLAMember(TimeStampedModel):
    class Gender(models.TextChoices):
        FEMALE = "female", "Female"
        MALE = "male", "Male"
        OTHER = "other", "Other / prefer not to say"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"
        EXITED = "exited", "Exited"
        DECEASED = "deceased", "Deceased"

    group = models.ForeignKey(VSLAGroup, on_delete=models.PROTECT, related_name="members")
    member_no = models.CharField(max_length=40, unique=True, blank=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    gender = models.CharField(max_length=10, choices=Gender.choices, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    national_id = models.CharField(max_length=80, blank=True)
    household_id = models.CharField(max_length=80, blank=True)
    village = models.CharField(max_length=160, blank=True)
    disability_inclusion = models.BooleanField(default=False)
    refugee_or_host_community = models.CharField(max_length=20, blank=True, choices=[("refugee", "Refugee"), ("host", "Host community"), ("other", "Other")])
    joined_on = models.DateField(default=timezone.localdate)
    exit_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    next_of_kin = models.CharField(max_length=160, blank=True)
    next_of_kin_phone = models.CharField(max_length=40, blank=True)
    consent_for_data = models.BooleanField(default=False, help_text="Record informed consent for collection and use of personal data.")
    notes = models.TextField(blank=True)
    registered_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="vsla_members_registered")

    class Meta:
        ordering = ["group__name", "last_name", "first_name"]
        indexes = [models.Index(fields=["group", "status"]), models.Index(fields=["last_name", "first_name"])]

    def save(self, *args, **kwargs):
        if not self.member_no:
            self.member_no = f"MEM-{timezone.localdate():%y%m}-{uuid4().hex[:7].upper()}"
        super().save(*args, **kwargs)

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    def __str__(self):
        return f"{self.full_name} ({self.member_no})"


class LedgerEntry(TimeStampedModel):
    class Status(models.TextChoices):
        POSTED = "posted", "Posted"
        VOID = "void", "Voided"

    transaction_ref = models.CharField(max_length=40, unique=True, blank=True, editable=False)
    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    transaction_date = models.DateField(default=timezone.localdate)
    receipt_no = models.CharField(max_length=80, blank=True)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.POSTED)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="%(class)s_recorded")
    voided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="%(class)s_voided")
    void_reason = models.TextField(blank=True)

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self.transaction_ref:
            self.transaction_ref = f"TX-{uuid4().hex[:12].upper()}"
        super().save(*args, **kwargs)


class SavingsTransaction(LedgerEntry):
    class Type(models.TextChoices):
        DEPOSIT = "deposit", "Weekly savings deposit"
        WITHDRAWAL = "withdrawal", "Approved withdrawal"
        SHARE_OUT = "share_out", "Cycle share-out"

    group = models.ForeignKey(VSLAGroup, on_delete=models.PROTECT, related_name="savings_transactions")
    member = models.ForeignKey(VSLAMember, on_delete=models.PROTECT, related_name="savings_transactions")
    transaction_type = models.CharField(max_length=12, choices=Type.choices, default=Type.DEPOSIT)
    week_ending = models.DateField(default=timezone.localdate)

    class Meta:
        ordering = ["-transaction_date", "-created_at"]
        indexes = [models.Index(fields=["group", "transaction_date"]), models.Index(fields=["member", "week_ending"])]

    def clean(self):
        if self.member_id and self.group_id and self.member.group_id != self.group_id:
            raise ValidationError("The selected member does not belong to this VSLA group.")
        if self.transaction_type == self.Type.WITHDRAWAL:
            available = self.member.savings_transactions.filter(status=LedgerEntry.Status.POSTED).aggregate(
                deposits=Sum("amount", filter=models.Q(transaction_type=self.Type.DEPOSIT)),
                withdrawals=Sum("amount", filter=models.Q(transaction_type__in=[self.Type.WITHDRAWAL, self.Type.SHARE_OUT])),
            )
            balance = (available["deposits"] or Decimal("0")) - (available["withdrawals"] or Decimal("0"))
            if self.pk:
                old = SavingsTransaction.objects.filter(pk=self.pk, status=LedgerEntry.Status.POSTED).first()
                if old and old.transaction_type == self.Type.WITHDRAWAL:
                    balance += old.amount
            if self.amount > balance:
                raise ValidationError("Withdrawal exceeds the member's available savings balance.")

    def __str__(self):
        return f"{self.transaction_ref} — {self.member}"


class Loan(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Pending review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        DISBURSED = "disbursed", "Disbursed"
        CLOSED = "closed", "Repaid / closed"
        DEFAULTED = "defaulted", "Defaulted"

    group = models.ForeignKey(VSLAGroup, on_delete=models.PROTECT, related_name="loans")
    member = models.ForeignKey(VSLAMember, on_delete=models.PROTECT, related_name="loans")
    loan_no = models.CharField(max_length=40, unique=True, blank=True)
    requested_amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("1"))])
    approved_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(Decimal("1"))])
    interest_rate = models.DecimalField(max_digits=5, decimal_places=2, validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))])
    duration_weeks = models.PositiveSmallIntegerField(default=12, validators=[MinValueValidator(1), MaxValueValidator(104)])
    purpose = models.TextField()
    application_date = models.DateField(default=timezone.localdate)
    due_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    decision_comment = models.TextField(blank=True)
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="vsla_loans_submitted")
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="vsla_loans_reviewed")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    disbursed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="vsla_loans_disbursed")
    disbursed_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-application_date", "-created_at"]
        permissions = [("review_vsla_loan", "Can review VSLA loan applications")]
        indexes = [models.Index(fields=["group", "status"]), models.Index(fields=["member", "status"])]

    def save(self, *args, **kwargs):
        if not self.loan_no:
            self.loan_no = f"LN-{timezone.localdate():%y%m}-{uuid4().hex[:7].upper()}"
        super().save(*args, **kwargs)

    def clean(self):
        if self.member_id and self.group_id and self.member.group_id != self.group_id:
            raise ValidationError("The selected member does not belong to this VSLA group.")

    @property
    def principal(self):
        return self.approved_amount if self.approved_amount is not None else self.requested_amount

    @property
    def interest_amount(self):
        return (self.principal * self.interest_rate / Decimal("100")).quantize(Decimal("0.01"))

    @property
    def total_due(self):
        return self.principal + self.interest_amount

    @property
    def total_repaid(self):
        return self.repayments.filter(status=LedgerEntry.Status.POSTED).aggregate(v=Sum("amount"))["v"] or Decimal("0")

    @property
    def outstanding_balance(self):
        return max(Decimal("0"), self.total_due - self.total_repaid)

    def __str__(self):
        return f"{self.loan_no} — {self.member}"


class LoanRepayment(LedgerEntry):
    loan = models.ForeignKey(Loan, on_delete=models.PROTECT, related_name="repayments")

    class Meta:
        ordering = ["-transaction_date", "-created_at"]
        indexes = [models.Index(fields=["loan", "transaction_date"])]

    def clean(self):
        if self.loan_id and self.loan.status not in [Loan.Status.DISBURSED, Loan.Status.CLOSED]:
            raise ValidationError("Repayments can only be recorded against a disbursed loan.")
        if self.loan_id and self.amount > self.loan.outstanding_balance:
            raise ValidationError("Repayment exceeds the outstanding loan balance.")

    def save(self, *args, **kwargs):
        self.full_clean()
        with transaction.atomic():
            super().save(*args, **kwargs)
            loan = Loan.objects.select_for_update().get(pk=self.loan_id)
            if loan.outstanding_balance <= 0 and loan.status == Loan.Status.DISBURSED:
                loan.status = Loan.Status.CLOSED
                loan.closed_at = timezone.now()
                loan.save(update_fields=["status", "closed_at", "updated_at"])


class VSLA_Meeting(TimeStampedModel):
    class Status(models.TextChoices):
        PLANNED = "planned", "Planned"
        HELD = "held", "Held"
        CANCELLED = "cancelled", "Cancelled"

    group = models.ForeignKey(VSLAGroup, on_delete=models.PROTECT, related_name="meetings")
    meeting_date = models.DateField(default=timezone.localdate)
    meeting_number = models.PositiveIntegerField(null=True, blank=True)
    venue = models.CharField(max_length=200, blank=True)
    agenda = models.TextField(blank=True)
    minutes = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PLANNED)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="vsla_meetings_recorded")

    class Meta:
        ordering = ["-meeting_date"]
        constraints = [models.UniqueConstraint(fields=["group", "meeting_date"], name="unique_vsla_group_meeting_date")]

    def __str__(self):
        return f"{self.group.name} — {self.meeting_date}"


class MeetingAttendance(TimeStampedModel):
    meeting = models.ForeignKey(VSLA_Meeting, on_delete=models.CASCADE, related_name="attendance")
    member = models.ForeignKey(VSLAMember, on_delete=models.PROTECT, related_name="meeting_attendance")
    present = models.BooleanField(default=True)
    remarks = models.CharField(max_length=250, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["meeting", "member"], name="unique_vsla_meeting_member")]

    def clean(self):
        if self.meeting_id and self.member_id and self.meeting.group_id != self.member.group_id:
            raise ValidationError("Attendance member must belong to the meeting's VSLA group.")


class SocialFundTransaction(LedgerEntry):
    class Type(models.TextChoices):
        CONTRIBUTION = "contribution", "Contribution"
        SUPPORT = "support", "Emergency support / payout"

    group = models.ForeignKey(VSLAGroup, on_delete=models.PROTECT, related_name="social_fund_transactions")
    member = models.ForeignKey(VSLAMember, null=True, blank=True, on_delete=models.PROTECT, related_name="social_fund_transactions")
    transaction_type = models.CharField(max_length=12, choices=Type.choices, default=Type.CONTRIBUTION)
    beneficiary_name = models.CharField(max_length=160, blank=True)

    class Meta:
        ordering = ["-transaction_date", "-created_at"]

    def clean(self):
        if self.member_id and self.group_id and self.member.group_id != self.group_id:
            raise ValidationError("The selected member does not belong to this VSLA group.")
