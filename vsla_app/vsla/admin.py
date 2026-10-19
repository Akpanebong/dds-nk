from django.contrib import admin
from .models import VSLAGroup, VSLAMember, SavingsTransaction, Loan, LoanRepayment, VSLA_Meeting, MeetingAttendance, SocialFundTransaction


@admin.register(VSLAGroup)
class VSLAGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "project_name", "district", "status", "start_date")
    list_filter = ("status", "district", "donor_name")
    search_fields = ("name", "code", "project_name", "donor_name")
    readonly_fields = ("code", "slug", "created_at", "updated_at")


@admin.register(VSLAMember)
class VSLAMemberAdmin(admin.ModelAdmin):
    list_display = ("member_no", "first_name", "last_name", "group", "gender", "phone", "status")
    list_filter = ("status", "gender", "refugee_or_host_community", "group")
    search_fields = ("member_no", "first_name", "last_name", "phone", "national_id")
    readonly_fields = ("member_no", "created_at", "updated_at")


@admin.register(SavingsTransaction)
class SavingsTransactionAdmin(admin.ModelAdmin):
    list_display = ("transaction_ref", "transaction_date", "group", "member", "transaction_type", "amount", "status", "recorded_by")
    list_filter = ("transaction_type", "status", "transaction_date", "group")
    search_fields = ("transaction_ref", "receipt_no", "member__first_name", "member__last_name")
    readonly_fields = ("transaction_ref", "created_at", "updated_at")


class LoanRepaymentInline(admin.TabularInline):
    model = LoanRepayment
    extra = 0
    readonly_fields = ("transaction_ref", "created_at", "updated_at")


@admin.register(Loan)
class LoanAdmin(admin.ModelAdmin):
    list_display = ("loan_no", "member", "group", "requested_amount", "approved_amount", "status", "application_date", "due_date")
    list_filter = ("status", "group", "application_date")
    search_fields = ("loan_no", "member__first_name", "member__last_name")
    readonly_fields = ("loan_no", "reviewed_at", "disbursed_at", "closed_at", "created_at", "updated_at")
    inlines = [LoanRepaymentInline]


@admin.register(LoanRepayment)
class LoanRepaymentAdmin(admin.ModelAdmin):
    list_display = ("transaction_ref", "loan", "transaction_date", "amount", "status", "recorded_by")
    readonly_fields = ("transaction_ref", "created_at", "updated_at")


@admin.register(VSLA_Meeting)
class VSLA_MeetingAdmin(admin.ModelAdmin):
    list_display = ("group", "meeting_date", "meeting_number", "status", "recorded_by")
    list_filter = ("status", "meeting_date", "group")


@admin.register(MeetingAttendance)
class MeetingAttendanceAdmin(admin.ModelAdmin):
    list_display = ("meeting", "member", "present")
    list_filter = ("present", "meeting__group")


@admin.register(SocialFundTransaction)
class SocialFundTransactionAdmin(admin.ModelAdmin):
    list_display = ("transaction_ref", "group", "transaction_date", "transaction_type", "member", "beneficiary_name", "amount", "status")
    list_filter = ("transaction_type", "status", "group")
    search_fields = ("transaction_ref", "beneficiary_name", "receipt_no")
    readonly_fields = ("transaction_ref", "created_at", "updated_at")
