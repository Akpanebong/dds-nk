import json
from decimal import Decimal
from datetime import timedelta
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum, Count
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .access import vsla_access_required
from .forms import VSLAGroupForm, VSLAMemberForm, SavingsTransactionForm, LoanForm, LoanRepaymentForm, VSLA_MeetingForm, SocialFundTransactionForm
from .models import VSLAGroup, VSLAMember, SavingsTransaction, Loan, LoanRepayment, VSLA_Meeting, SocialFundTransaction, LedgerEntry


# @vsla_access_required
# def dashboard(request):
#     groups = VSLAGroup.objects.all()
#     members = VSLAMember.objects.all()
#     loans = Loan.objects.all()
#     savings = SavingsTransaction.objects.filter(status=LedgerEntry.Status.POSTED)
#     total_savings = savings.filter(transaction_type=SavingsTransaction.Type.DEPOSIT).aggregate(v=Sum("amount"))["v"] or Decimal("0")
#     withdrawals = savings.filter(transaction_type__in=[SavingsTransaction.Type.WITHDRAWAL, SavingsTransaction.Type.SHARE_OUT]).aggregate(v=Sum("amount"))["v"] or Decimal("0")
#     loan_disbursed = Loan.objects.filter(status__in=[Loan.Status.DISBURSED, Loan.Status.CLOSED]).aggregate(v=Sum("approved_amount"))["v"] or Decimal("0")
#     outstanding = sum((loan.outstanding_balance for loan in loans.filter(status=Loan.Status.DISBURSED)), Decimal("0"))
#     social = SocialFundTransaction.objects.filter(status=LedgerEntry.Status.POSTED)
#     social_in = social.filter(transaction_type=SocialFundTransaction.Type.CONTRIBUTION).aggregate(v=Sum("amount"))["v"] or Decimal("0")
#     social_out = social.filter(transaction_type=SocialFundTransaction.Type.SUPPORT).aggregate(v=Sum("amount"))["v"] or Decimal("0")
#     month_start = timezone.localdate().replace(day=1)
#     recent_savings = savings.select_related("group", "member").order_by("-transaction_date", "-created_at")[:8]
#     recent_loans = loans.select_related("group", "member").order_by("-created_at")[:6]
#     status_counts = list(groups.values("status").annotate(total=Count("id")).order_by("status"))
#     chart_data = {
#         "groupLabels": [item["status"].replace("_", " ").title() for item in status_counts],
#         "groupValues": [item["total"] for item in status_counts],
#         "savingsLabels": ["Deposits", "Withdrawals / share-outs"],
#         "savingsValues": [float(total_savings), float(withdrawals)],
#         "loanLabels": ["Outstanding", "Repaid"],
#         "loanValues": [float(outstanding), float(max(Decimal("0"), loan_disbursed - outstanding))],
#     }
#     context = {
#         "title": "VSLA Intelligence Dashboard",
#         "total_groups": groups.count(),
#         "active_groups": groups.filter(status=VSLAGroup.Status.ACTIVE).count(),
#         "active_members": members.filter(status=VSLAMember.Status.ACTIVE).count(),
#         "total_members": members.count(),
#         "total_savings": total_savings,
#         "net_savings": total_savings - withdrawals,
#         "loan_disbursed": loan_disbursed,
#         "outstanding_loans": outstanding,
#         "pending_loans": loans.filter(status=Loan.Status.SUBMITTED).count(),
#         "social_fund_balance": social_in - social_out,
#         "recent_savings": recent_savings,
#         "recent_loans": recent_loans,
#         "chart_data": chart_data,
#     }
#     return render(request, "vsla/dashboard.html", context)

from decimal import Decimal

from django.db.models import (
    Count,
    Sum,
    Q,
    F,
    Value,
    Case,
    When,
    OuterRef,
    Subquery,
    ExpressionWrapper,
    DecimalField,
)
from django.db.models.functions import Coalesce
from django.shortcuts import render


@vsla_access_required
def dashboard(request):
    """Optimized VSLA dashboard with database-side portfolio calculations."""

    ZERO = Decimal("0.00")
    MONEY = DecimalField(max_digits=18, decimal_places=2)

    zero_value = Value(ZERO, output_field=MONEY)
    hundred_value = Value(Decimal("100"), output_field=MONEY)

    # ---------------------------------------------------------
    # 1. Groups and members
    # ---------------------------------------------------------
    group_stats = VSLAGroup.objects.aggregate(
        total_groups=Count("pk"),
        active_groups=Count(
            "pk",
            filter=Q(status=VSLAGroup.Status.ACTIVE),
        ),
    )

    member_stats = VSLAMember.objects.aggregate(
        total_members=Count("pk"),
        active_members=Count(
            "pk",
            filter=Q(status=VSLAMember.Status.ACTIVE),
        ),
    )

    # ---------------------------------------------------------
    # 2. Posted savings
    # ---------------------------------------------------------
    posted_savings = SavingsTransaction.objects.filter(
        status=LedgerEntry.Status.POSTED,
    )

    savings_stats = posted_savings.aggregate(
        total_savings=Sum(
            "amount",
            filter=Q(
                transaction_type=SavingsTransaction.Type.DEPOSIT,
            ),
        ),
        withdrawals=Sum(
            "amount",
            filter=Q(
                transaction_type__in=[
                    SavingsTransaction.Type.WITHDRAWAL,
                    SavingsTransaction.Type.SHARE_OUT,
                ],
            ),
        ),
    )

    total_savings = savings_stats["total_savings"] or ZERO
    withdrawals = savings_stats["withdrawals"] or ZERO
    net_savings = total_savings - withdrawals

    # ---------------------------------------------------------
    # 3. Loan portfolio
    # ---------------------------------------------------------
    # Calculate posted repayments per loan in a correlated
    # subquery, avoiding a query for every loan property.
    repayment_totals = (
        LoanRepayment.objects.filter(
            loan_id=OuterRef("pk"),
            status=LedgerEntry.Status.POSTED,
        )
        .order_by()
        .values("loan_id")
        .annotate(total=Sum("amount"))
        .values("total")[:1]
    )

    loan_portfolio = Loan.objects.annotate(
        dashboard_principal=Coalesce(
            "approved_amount",
            "requested_amount",
            output_field=MONEY,
        ),
        dashboard_repaid=Coalesce(
            Subquery(repayment_totals, output_field=MONEY),
            zero_value,
            output_field=MONEY,
        ),
    ).annotate(
        dashboard_total_due=ExpressionWrapper(
            F("dashboard_principal")
            * (
                hundred_value + F("interest_rate")
            )
            / hundred_value,
            output_field=MONEY,
        ),
    ).annotate(
        dashboard_outstanding=Case(
            When(
                dashboard_total_due__gt=F("dashboard_repaid"),
                then=ExpressionWrapper(
                    F("dashboard_total_due") - F("dashboard_repaid"),
                    output_field=MONEY,
                ),
            ),
            default=zero_value,
            output_field=MONEY,
        ),
    )

    loan_stats = loan_portfolio.aggregate(
        loan_disbursed=Sum(
            "approved_amount",
            filter=Q(
                status__in=[
                    Loan.Status.DISBURSED,
                    Loan.Status.CLOSED,
                ],
            ),
        ),
        outstanding=Sum(
            "dashboard_outstanding",
            filter=Q(status=Loan.Status.DISBURSED),
        ),
        pending_loans=Count(
            "pk",
            filter=Q(status=Loan.Status.SUBMITTED),
        ),
    )

    loan_disbursed = loan_stats["loan_disbursed"] or ZERO
    outstanding = loan_stats["outstanding"] or ZERO

    # Actual posted repayments, rather than estimating repayment
    # as disbursed principal minus outstanding principal.
    total_repaid = (
        LoanRepayment.objects.filter(
            status=LedgerEntry.Status.POSTED,
            loan__status__in=[
                Loan.Status.DISBURSED,
                Loan.Status.CLOSED,
            ],
        ).aggregate(total=Sum("amount"))["total"]
        or ZERO
    )

    # ---------------------------------------------------------
    # 4. Social fund
    # ---------------------------------------------------------
    social_stats = SocialFundTransaction.objects.filter(
        status=LedgerEntry.Status.POSTED,
    ).aggregate(
        social_in=Sum(
            "amount",
            filter=Q(
                transaction_type=SocialFundTransaction.Type.CONTRIBUTION,
            ),
        ),
        social_out=Sum(
            "amount",
            filter=Q(
                transaction_type=SocialFundTransaction.Type.SUPPORT,
            ),
        ),
    )

    social_in = social_stats["social_in"] or ZERO
    social_out = social_stats["social_out"] or ZERO
    social_fund_balance = social_in - social_out

    # ---------------------------------------------------------
    # 5. Group status chart
    # ---------------------------------------------------------
    status_counts = list(
        VSLAGroup.objects.values("status")
        .annotate(total=Count("pk"))
        .order_by("status")
    )

    # ---------------------------------------------------------
    # 6. Recent posted savings and recent loan applications
    # ---------------------------------------------------------
    recent_savings = (
        posted_savings.select_related("group", "member")
        .order_by("-transaction_date", "-created_at")[:8]
    )

    recent_loans = (
        Loan.objects.select_related("group", "member")
        .order_by("-created_at")[:6]
    )

    # ---------------------------------------------------------
    # 7. Chart data
    # ---------------------------------------------------------
    chart_data = {
        "groupLabels": [
            (item["status"] or "unknown")
            .replace("_", " ")
            .title()
            for item in status_counts
        ],
        "groupValues": [
            item["total"] for item in status_counts
        ],
        "savingsLabels": [
            "Deposits",
            "Withdrawals / share-outs",
        ],
        "savingsValues": [
            float(total_savings),
            float(withdrawals),
        ],
        "loanLabels": [
            "Outstanding",
            "Posted repayments",
        ],
        "loanValues": [
            float(outstanding),
            float(total_repaid),
        ],
    }

    # ---------------------------------------------------------
    # 8. Template context — preserve existing variable names
    # ---------------------------------------------------------
    context = {
        "title": "VSLA Intelligence Dashboard",

        "total_groups": group_stats["total_groups"],
        "active_groups": group_stats["active_groups"],

        "total_members": member_stats["total_members"],
        "active_members": member_stats["active_members"],

        "total_savings": total_savings,
        "net_savings": net_savings,

        "loan_disbursed": loan_disbursed,
        "outstanding_loans": outstanding,
        "pending_loans": loan_stats["pending_loans"],

        "social_fund_balance": social_fund_balance,

        "recent_savings": recent_savings,
        "recent_loans": recent_loans,

        "chart_data": chart_data,
    }

    return render(request, "vsla/dashboard.html", context)


@vsla_access_required
def group_list(request):
    qs = VSLAGroup.objects.annotate(member_total=Count("members")).order_by("name")
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(name__icontains=q) | qs.filter(code__icontains=q) | qs.filter(district__icontains=q)
    return render(request, "vsla/group_list.html", {"groups": qs, "q": q, "title": "VSLA Groups"})


@vsla_access_required
def group_create(request):
    form = VSLAGroupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.created_by = request.user
        obj.save()
        messages.success(request, "VSLA group registered successfully.")
        return redirect("vsla:group_detail", slug=obj.slug)
    return render(request, "vsla/form.html", {"form": form, "title": "Register VSLA Group", "eyebrow": "GROUP MANAGEMENT", "cancel_url": "vsla:groups"})


@vsla_access_required
def group_detail(request, slug):
    group = get_object_or_404(VSLAGroup, slug=slug)
    members = group.members.all()
    transactions = group.savings_transactions.select_related("member", "recorded_by").order_by("-transaction_date")[:12]
    loans = group.loans.select_related("member").order_by("-created_at")[:10]
    deposits = group.savings_transactions.filter(status=LedgerEntry.Status.POSTED, transaction_type=SavingsTransaction.Type.DEPOSIT).aggregate(v=Sum("amount"))["v"] or Decimal("0")
    withdrawals = group.savings_transactions.filter(status=LedgerEntry.Status.POSTED, transaction_type__in=[SavingsTransaction.Type.WITHDRAWAL, SavingsTransaction.Type.SHARE_OUT]).aggregate(v=Sum("amount"))["v"] or Decimal("0")
    return render(request, "vsla/group_detail.html", {"group": group, "members": members, "transactions": transactions, "loans": loans, "group_savings": deposits-withdrawals, "title": group.name})


@vsla_access_required
def member_list(request):
    qs = VSLAMember.objects.select_related("group").all()
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(first_name__icontains=q) | qs.filter(last_name__icontains=q) | qs.filter(member_no__icontains=q) | qs.filter(phone__icontains=q)
    group_id = request.GET.get("group")
    if group_id:
        qs = qs.filter(group_id=group_id)
    return render(request, "vsla/member_list.html", {"members": qs, "groups": VSLAGroup.objects.order_by("name"), "q": q, "selected_group": group_id, "title": "VSLA Members"})


@vsla_access_required
def member_create(request):
    form = VSLAMemberForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.registered_by = request.user
        obj.save()
        messages.success(request, f"{obj.full_name} was registered successfully.")
        return redirect("vsla:member_detail", member_no=obj.member_no)
    return render(request, "vsla/form.html", {"form": form, "title": "Register Member", "eyebrow": "MEMBER REGISTRY", "cancel_url": "vsla:members"})


@vsla_access_required
def member_detail(request, member_no):
    member = get_object_or_404(VSLAMember.objects.select_related("group"), member_no=member_no)
    savings = member.savings_transactions.order_by("-transaction_date", "-created_at")[:20]
    loans = member.loans.order_by("-created_at")
    total_saved = member.savings_transactions.filter(status=LedgerEntry.Status.POSTED, transaction_type=SavingsTransaction.Type.DEPOSIT).aggregate(v=Sum("amount"))["v"] or Decimal("0")
    total_out = member.savings_transactions.filter(status=LedgerEntry.Status.POSTED, transaction_type__in=[SavingsTransaction.Type.WITHDRAWAL, SavingsTransaction.Type.SHARE_OUT]).aggregate(v=Sum("amount"))["v"] or Decimal("0")
    return render(request, "vsla/member_detail.html", {"member": member, "savings": savings, "loans": loans, "member_balance": total_saved-total_out, "title": member.full_name})


@vsla_access_required
def savings_list(request):
    qs = SavingsTransaction.objects.select_related("group", "member", "recorded_by").all()
    group_id = request.GET.get("group")
    if group_id:
        qs = qs.filter(group_id=group_id)
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(member__first_name__icontains=q) | qs.filter(member__last_name__icontains=q) | qs.filter(transaction_ref__icontains=q) | qs.filter(receipt_no__icontains=q)
    return render(request, "vsla/savings_list.html", {"transactions": qs[:250], "groups": VSLAGroup.objects.order_by("name"), "q": q, "selected_group": group_id, "title": "Weekly Savings Ledger"})


@vsla_access_required
def savings_create(request):
    initial = {}
    member_id = request.GET.get("member")
    group_id = request.GET.get("group")
    if member_id:
        selected_member = VSLAMember.objects.select_related("group").filter(pk=member_id).first()
        if selected_member:
            initial.update(member=selected_member.pk, group=selected_member.group_id)
    elif group_id:
        initial["group"] = group_id
    form = SavingsTransactionForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.recorded_by = request.user
        try:
            obj.full_clean()
            obj.save()
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, f"Savings transaction {obj.transaction_ref} recorded.")
            return redirect("vsla:savings")
    return render(request, "vsla/form.html", {"form": form, "title": "Record Weekly Savings", "eyebrow": "SAVINGS LEDGER", "cancel_url": "vsla:savings"})


@vsla_access_required
def loan_list(request):
    qs = Loan.objects.select_related("group", "member", "reviewed_by").all()
    status = request.GET.get("status")
    if status:
        qs = qs.filter(status=status)
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(loan_no__icontains=q) | qs.filter(member__first_name__icontains=q) | qs.filter(member__last_name__icontains=q)
    return render(request, "vsla/loan_list.html", {"loans": qs[:250], "q": q, "selected_status": status, "statuses": Loan.Status.choices, "title": "Loan Portfolio"})


@vsla_access_required
def loan_create(request):
    initial = {}
    member_id = request.GET.get("member")
    group_id = request.GET.get("group")
    if member_id:
        selected_member = VSLAMember.objects.select_related("group").filter(pk=member_id).first()
        if selected_member:
            initial.update(member=selected_member.pk, group=selected_member.group_id)
    elif group_id:
        initial["group"] = group_id
    form = LoanForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.submitted_by = request.user
        obj.save()
        messages.success(request, f"Loan application {obj.loan_no} saved as draft.")
        return redirect("vsla:loan_detail", loan_no=obj.loan_no)
    return render(request, "vsla/form.html", {"form": form, "title": "New Loan Application", "eyebrow": "CREDIT MANAGEMENT", "cancel_url": "vsla:loans"})


@vsla_access_required
def loan_detail(request, loan_no):
    loan = get_object_or_404(Loan.objects.select_related("group", "member"), loan_no=loan_no)
    repayments = loan.repayments.filter(status=LedgerEntry.Status.POSTED).order_by("-transaction_date")
    return render(request, "vsla/loan_detail.html", {"loan": loan, "repayments": repayments, "repayment_form": LoanRepaymentForm(), "title": loan.loan_no})


@vsla_access_required
@require_POST
def loan_submit(request, loan_no):
    loan = get_object_or_404(Loan, loan_no=loan_no)
    if loan.status != Loan.Status.DRAFT:
        messages.error(request, "Only draft loan applications can be submitted.")
    else:
        loan.status = Loan.Status.SUBMITTED
        loan.save(update_fields=["status", "updated_at"])
        messages.success(request, "Loan application submitted for review.")
    return redirect("vsla:loan_detail", loan_no=loan_no)


@vsla_access_required
@require_POST
def loan_decision(request, loan_no):
    if not (request.user.has_perm("vsla.review_vsla_loan") or request.user.has_perm("vsla.approve_vsla_loan") or request.user.is_superuser or request.user.is_staff):
        return HttpResponseForbidden("You do not have permission to review loans.")
    loan = get_object_or_404(Loan, loan_no=loan_no)
    decision = request.POST.get("decision")
    comment = request.POST.get("comment", "").strip()
    if decision in {"approve", "reject"} and loan.status != Loan.Status.SUBMITTED:
        messages.error(request, "Only submitted loan applications can be reviewed.")
    elif decision == "approve":
        try:
            amount = Decimal(request.POST.get("approved_amount") or loan.requested_amount)
            if amount <= 0 or amount > loan.requested_amount:
                raise ValueError
        except (ValueError, ArithmeticError):
            messages.error(request, "Enter a valid approved amount not exceeding the requested amount.")
            return redirect("vsla:loan_detail", loan_no=loan_no)
        loan.approved_amount = amount
        loan.status = Loan.Status.APPROVED
        loan.reviewed_by = request.user
        loan.reviewed_at = timezone.now()
        loan.decision_comment = comment
        loan.save()
        messages.success(request, "Loan approved. Record disbursement when funds are issued.")
    elif decision == "reject":
        loan.status = Loan.Status.REJECTED
        loan.reviewed_by = request.user
        loan.reviewed_at = timezone.now()
        loan.decision_comment = comment
        loan.save()
        messages.success(request, "Loan application rejected.")
    elif decision == "disburse":
        if loan.status != Loan.Status.APPROVED:
            messages.error(request, "Only approved loans can be disbursed.")
        else:
            loan.status = Loan.Status.DISBURSED
            loan.disbursed_by = request.user
            loan.disbursed_at = timezone.now()
            loan.due_date = timezone.localdate() + timedelta(weeks=loan.duration_weeks)
            loan.save()
            messages.success(request, "Loan marked as disbursed.")
    else:
        messages.error(request, "Unknown loan decision.")
    return redirect("vsla:loan_detail", loan_no=loan_no)


@vsla_access_required
@require_POST
def repayment_create(request, loan_no):
    loan = get_object_or_404(Loan, loan_no=loan_no)
    form = LoanRepaymentForm(request.POST)
    if form.is_valid():
        obj = form.save(commit=False)
        obj.loan = loan
        obj.recorded_by = request.user
        try:
            obj.full_clean()
            obj.save()
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        else:
            messages.success(request, "Loan repayment recorded.")
    else:
        messages.error(request, "Please correct the repayment details.")
    return redirect("vsla:loan_detail", loan_no=loan_no)


@vsla_access_required
def meeting_list(request):
    meetings = VSLA_Meeting.objects.select_related("group", "recorded_by").all()
    return render(request, "vsla/meeting_list.html", {"meetings": meetings[:200], "title": "Group Meetings"})


@vsla_access_required
def meeting_create(request):
    form = VSLA_MeetingForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.recorded_by = request.user
        obj.save()
        messages.success(request, "Meeting recorded.")
        return redirect("vsla:meetings")
    return render(request, "vsla/form.html", {"form": form, "title": "Record Group Meeting", "eyebrow": "MEETING MANAGEMENT", "cancel_url": "vsla:meetings"})


@vsla_access_required
def social_fund_list(request):
    txs = SocialFundTransaction.objects.select_related("group", "member", "recorded_by").all()[:250]
    return render(request, "vsla/social_fund_list.html", {"transactions": txs, "title": "Social Fund Ledger"})


@vsla_access_required
def social_fund_create(request):
    initial = {}
    member_id = request.GET.get("member")
    group_id = request.GET.get("group")
    if member_id:
        selected_member = VSLAMember.objects.select_related("group").filter(pk=member_id).first()
        if selected_member:
            initial.update(member=selected_member.pk, group=selected_member.group_id)
    elif group_id:
        initial["group"] = group_id
    form = SocialFundTransactionForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.recorded_by = request.user
        try:
            obj.full_clean()
            obj.save()
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "Social fund transaction recorded.")
            return redirect("vsla:social_fund")
    return render(request, "vsla/form.html", {"form": form, "title": "Record Social Fund Transaction", "eyebrow": "SOCIAL PROTECTION", "cancel_url": "vsla:social_fund"})
