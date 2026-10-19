from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.mail import send_mail
from django.core.paginator import Paginator
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.generic import DetailView, UpdateView
from core.models import StaffProfile as Profile
from .orientation_models import OrientationPlan, OrientationSession
from .utils import notify, _send_html_email
from .models import Employee, Attendance, Leave, LeaveSchedule, \
    Training, SituationReport, LeaveType
from django.contrib.auth.decorators import login_required,  user_passes_test
from .forms import EmployeeForm, LeaveForm, AttendanceForm, TrainingForm, \
    SituationReportForm, UpdateSitrepStatusForm,\
    StaffAttendanceForm, LeaveScheduleForm
from django.contrib import messages
from django.http import HttpResponse, HttpResponseForbidden
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from django.utils.dateparse import parse_date
import os
from openpyxl.styles import Font, Alignment
from openpyxl import Workbook
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.core.mail import EmailMultiAlternatives
from datetime import date, datetime
from django.utils.timezone import now, timedelta
from django.db.models import Avg, Count, Q
from .utils import (render_to_pdf, yearly_leave_allocation_report, staff_leave_balance_report, employee_leave_balances,
                    logo_path, )
from core.access import signature_required
from .models import (Attendance, Leave, LeaveType, Training, SituationReport, StaffDevice,)
from core.models import StaffProfile, Department

import logging

from ..appraisals.models import Appraisal, PerformanceImprovementPlan

logger = logging.getLogger(__name__)

# User = get_user_model()


def is_cmt_user(user):
    return is_ed(user)


def leave_signer_conflict(*, requester, previous_signers):
    """Prevent the leave requester from also acting as an approver."""
    if not requester:
        return False
    return any(
        signer is not None and signer.pk == requester.pk
        for signer in previous_signers
    )


def _notify_leave_recipients(*, request, leave, recipients, title, message, category):
    """Create an in-app leave notification and attempt email delivery."""
    recipients = list(dict.fromkeys(user for user in recipients if user))
    if not recipients:
        return

    action_url = request.build_absolute_uri(
        reverse("hr:leave_detail", kwargs={"slug": leave.slug})
    )
    notify(
        request=request,
        users=recipients,
        title=title,
        message=message,
        category=category,
        source_app="hr",
        action_url=action_url,
    )

    email_message = f"{message}\n\nOpen the leave request: {action_url}"
    for recipient in recipients:
        if not recipient.email:
            continue
        try:
            send_mail(
                subject=title,
                message=email_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[recipient.email],
                fail_silently=False,
            )
        except Exception:
            logger.exception("Unable to email leave notification to %s", recipient.email)


# helper access checks (customize to your groups/permissions)
def is_supervisor(user):
    return bool(
        user
        and (
            user.is_superuser
            or user.groups.filter(name="Supervisor").exists()
            or user.supervised_staff.exists()
        )
    )


def is_hr(user):
    return (
        bool(user)
        and (
            user.is_superuser
            or (
                (user.groups.filter(name="HR").exists() or
                 user.groups.filter(name="ED").exists() or
                  user.groups.filter(name="Human Resources").exists() or
                  user.groups.filter(name="Executive Director").exists())
            )
        )
    )


def is_ed(user):
    return bool(user and (user.groups.filter(name="ED").exists() or user.is_superuser))


def is_cmt(user):
    # CMT is not a separate role in this organisation; ED owns that workflow.
    return is_ed(user)


def is_department_head(user):
    return bool(user and (user.is_superuser or getattr(user, "department_id", None) and user.department.head_id == user.pk))


@login_required(login_url="login")
# @hr_access_required
def dashboard(request):
    """HR workforce, compliance, performance and onboarding dashboard."""
    # if not is_hr(request.user):
    #     messages.info(request, "Access Denied.")
    #     return redirect("hr:profile")

    today = timezone.localdate()
    now = timezone.now()
    week_start = today - timedelta(days=6)

    # ---------------------------------------------------------
    # WORKFORCE
    # ---------------------------------------------------------
    workforce = StaffProfile.objects.all()

    workforce_stats = workforce.aggregate(
        total=Count("pk"),
        active=Count("pk", filter=Q(is_active=True, status="Active")),
        on_leave=Count("pk", filter=Q(is_active=True, status="On Leave")),
        exited=Count("pk", filter=Q(status="Exit")),
        volunteers=Count(
            "pk",
            filter=Q(is_active=True, user_type=StaffProfile.UserType.VOLUNTEER),
        ),
        interns=Count(
            "pk",
            filter=Q(is_active=True, user_type=StaffProfile.UserType.INTERN),
        ),
    )

    departments = Department.objects.annotate(
        staff_count=Count(
            "staff",
            filter=Q(staff__is_active=True),
            distinct=True,
        )
    ).order_by("-staff_count", "name")

    department_labels = list(
        departments.values_list("name", flat=True)[:8]
    )
    department_values = list(
        departments.values_list("staff_count", flat=True)[:8]
    )

    # ---------------------------------------------------------
    # ATTENDANCE — logs recorded today
    # ---------------------------------------------------------
    attendance_today = Attendance.objects.filter(date__date=today)

    attendance_stats = attendance_today.aggregate(
        records=Count("pk"),
        present=Count("pk", filter=Q(status="Present")),
        absent=Count("pk", filter=Q(status="Absent")),
        leave=Count("pk", filter=Q(status="Leave")),
        staff_recorded=Count("employee", distinct=True),
    )

    attendance_trend = []
    for offset in range(6, -1, -1):
        day = today - timedelta(days=offset)
        day_stats = Attendance.objects.filter(date__date=day).aggregate(
            present=Count("pk", filter=Q(status="Present")),
            absent=Count("pk", filter=Q(status="Absent")),
            leave=Count("pk", filter=Q(status="Leave")),
        )
        attendance_trend.append({
            "label": day.strftime("%a"),
            "present": day_stats["present"] or 0,
            "absent": day_stats["absent"] or 0,
            "leave": day_stats["leave"] or 0,
        })

    # ---------------------------------------------------------
    # LEAVE WORKFLOW
    # ---------------------------------------------------------
    leaves = Leave.objects.select_related(
        "employee",
        "leave_type",
        "special_type",
        "supervisor",
    )

    leave_stats = leaves.aggregate(
        total=Count("pk"),
        pending=Count("pk", filter=Q(status="Pending")),
        supervisor_approved=Count(
            "pk", filter=Q(status="SupervisorApproved")
        ),
        hr_approved=Count("pk", filter=Q(status="HRApproved")),
        approved=Count("pk", filter=Q(status="Approved")),
        denied=Count("pk", filter=Q(status="Denied")),
    )

    pending_leave_count = (
        leave_stats["pending"]
        + leave_stats["supervisor_approved"]
        + leave_stats["hr_approved"]
    )

    upcoming_leave_count = leaves.filter(
        status="Approved",
        start_date__gte=today,
        start_date__lte=today + timedelta(days=30),
    ).count()

    currently_on_leave_count = leaves.filter(
        status="Approved",
        start_date__lte=today,
        end_date__gte=today,
    ).count()

    # ---------------------------------------------------------
    # PERFORMANCE APPRAISALS
    # ---------------------------------------------------------
    appraisals = Appraisal.objects.select_related(
        "employee",
        "supervisor",
    )

    appraisal_stats = appraisals.aggregate(
        total=Count("pk"),
        draft=Count("pk", filter=Q(status="draft")),
        sent_to_employee=Count(
            "pk", filter=Q(status="sent_to_employee")
        ),
        submitted_by_employee=Count(
            "pk", filter=Q(status="submitted_by_employee")
        ),
        reviewed_by_supervisor=Count(
            "pk", filter=Q(status="reviewed_by_supervisor")
        ),
        reviewed_by_hr=Count(
            "pk", filter=Q(status="reviewed_by_hr")
        ),
        approved=Count("pk", filter=Q(status="approved")),
    )

    appraisal_action_count = (
        appraisal_stats["sent_to_employee"]
        + appraisal_stats["submitted_by_employee"]
        + appraisal_stats["reviewed_by_supervisor"]
        + appraisal_stats["reviewed_by_hr"]
    )

    # ---------------------------------------------------------
    # PERFORMANCE IMPROVEMENT PLANS
    # ---------------------------------------------------------
    pips = PerformanceImprovementPlan.objects.select_related(
        "employee",
        "appraisal",
    )

    pip_stats = pips.aggregate(
        total=Count("pk"),
        draft=Count("pk", filter=Q(status="draft")),
        sent=Count("pk", filter=Q(status="sent_to_staff")),
        submitted=Count("pk", filter=Q(status="submitted_by_staff")),
        under_hr_review=Count("pk", filter=Q(status="reviewed_by_hr")),
        completed=Count("pk", filter=Q(status="completed")),
    )

    overdue_pips = pips.filter(
        expected_completion_date__lt=today,
    ).exclude(status="completed").count()

    # ---------------------------------------------------------
    # ORIENTATION / ONBOARDING
    # ---------------------------------------------------------
    orientation_plans = OrientationPlan.objects.select_related("staff")

    orientation_stats = orientation_plans.aggregate(
        total=Count("pk"),
        in_progress=Count("pk", filter=Q(status="in_progress")),
        completed=Count("pk", filter=Q(status="completed")),
        canceled=Count("pk", filter=Q(status="canceled")),
    )

    orientation_sessions = OrientationSession.objects.select_related(
        "plan__staff",
        "department",
    )

    session_stats = orientation_sessions.aggregate(
        total=Count("pk"),
        awaiting_schedule=Count(
            "pk", filter=Q(status="awaiting_schedule")
        ),
        scheduled=Count("pk", filter=Q(status="scheduled")),
        completed=Count("pk", filter=Q(status="completed")),
    )

    upcoming_orientation_sessions = orientation_sessions.filter(
        status="scheduled",
        scheduled_start__gte=now,
        scheduled_start__lte=now + timedelta(days=14),
    ).order_by("scheduled_start")[:6]

    # ---------------------------------------------------------
    # TRAINING
    # ---------------------------------------------------------
    trainings = Training.objects.all()

    training_stats = trainings.aggregate(
        total=Count("pk"),
        upcoming=Count(
            "pk",
            filter=Q(start_date__gt=today),
        ),
        ongoing=Count(
            "pk",
            filter=Q(start_date__lte=today, end_date__gte=today),
        ),
        completed=Count(
            "pk",
            filter=Q(end_date__lt=today),
        ),
    )

    upcoming_trainings = trainings.filter(
        end_date__gte=today,
    ).order_by("start_date")[:5]

    # ---------------------------------------------------------
    # ORGANIZATIONAL OPERATIONS / SECURITY
    # ---------------------------------------------------------
    situation_stats = SituationReport.objects.aggregate(
        total=Count("pk"),
        pending=Count("pk", filter=Q(status="Pending")),
        reviewed=Count("pk", filter=Q(status="Reviewed")),
        resolved=Count("pk", filter=Q(status="Resolved")),
    )

    device_stats = StaffDevice.objects.aggregate(
        total=Count("pk"),
        pending=Count("pk", filter=Q(approved=False)),
        approved=Count("pk", filter=Q(approved=True)),
    )

    # ---------------------------------------------------------
    # RECENT RECORDS
    # ---------------------------------------------------------
    recent_staff = workforce.select_related(
        "department",
    ).order_by("-date_joined", "-pk")[:8]

    recent_leaves = leaves.order_by("-applied_date")[:6]

    recent_appraisals = appraisals.order_by("-created_at")[:6]

    recent_sitreps = SituationReport.objects.select_related(
        "reporter",
    ).order_by("-created_at")[:5]

    # ---------------------------------------------------------
    # CHART DATA
    # ---------------------------------------------------------
    leave_chart_labels = [
        "Pending",
        "Supervisor approved",
        "HR approved",
        "Approved",
        "Denied",
    ]
    leave_chart_values = [
        leave_stats["pending"],
        leave_stats["supervisor_approved"],
        leave_stats["hr_approved"],
        leave_stats["approved"],
        leave_stats["denied"],
    ]

    appraisal_chart_labels = [
        "Draft",
        "Sent to employee",
        "Submitted",
        "Supervisor review",
        "HR review",
        "Approved",
    ]
    appraisal_chart_values = [
        appraisal_stats["draft"],
        appraisal_stats["sent_to_employee"],
        appraisal_stats["submitted_by_employee"],
        appraisal_stats["reviewed_by_supervisor"],
        appraisal_stats["reviewed_by_hr"],
        appraisal_stats["approved"],
    ]

    chart_data = {
        "departmentLabels": department_labels,
        "departmentValues": department_values,
        "attendanceLabels": [item["label"] for item in attendance_trend],
        "attendancePresent": [item["present"] for item in attendance_trend],
        "attendanceAbsent": [item["absent"] for item in attendance_trend],
        "attendanceLeave": [item["leave"] for item in attendance_trend],
        "leaveLabels": leave_chart_labels,
        "leaveValues": leave_chart_values,
        "appraisalLabels": appraisal_chart_labels,
        "appraisalValues": appraisal_chart_values,
    }

    context = {
        # Workforce
        "staff": workforce_stats["total"],
        "active": workforce_stats["active"],
        "on_leave_staff": workforce_stats["on_leave"],
        "exited_staff": workforce_stats["exited"],
        "volunteers": workforce_stats["volunteers"],
        "interns": workforce_stats["interns"],
        "department_count": Department.objects.count(),
        "departments": departments[:8],

        # Attendance
        "attendance_records_today": attendance_stats["records"],
        "attendance_staff_recorded": attendance_stats["staff_recorded"],
        "attendance_present": attendance_stats["present"],
        "attendance_absent": attendance_stats["absent"],
        "attendance_leave": attendance_stats["leave"],

        # Leave
        "leave_stats": leave_stats,
        "pending_leave_count": pending_leave_count,
        "upcoming_leave_count": upcoming_leave_count,
        "currently_on_leave_count": currently_on_leave_count,
        "recent_leaves": recent_leaves,

        # Performance
        "reviews": appraisal_stats["total"],
        "appraisal_stats": appraisal_stats,
        "appraisal_action_count": appraisal_action_count,
        "pip_stats": pip_stats,
        "overdue_pips": overdue_pips,
        "recent_appraisals": recent_appraisals,

        # Onboarding
        "orientation_stats": orientation_stats,
        "session_stats": session_stats,
        "upcoming_orientation_sessions": upcoming_orientation_sessions,

        # Training
        "training_stats": training_stats,
        "upcoming_trainings": upcoming_trainings,

        # Operations and security
        "situation_stats": situation_stats,
        "device_stats": device_stats,
        "recent_sitreps": recent_sitreps,

        # Recent staff and visualization
        "recent": recent_staff,
        "chart_data": chart_data,
        "today": today,
        "last_updated": now,
    }

    return render(request, "hr/dashboard.html", context)


@login_required(login_url='login')
def employee_list(request):
    if not (is_hr(request.user) or is_supervisor(request.user) or request.user.is_superuser):
        messages.error(request, "You are not authorized to view this page.")
        return redirect('hr:profile')

    search_query = request.GET.get("q", "").strip()
    staff_qs = Employee.objects.filter(is_active=True).select_related("department")
    if search_query:
        staff_qs = staff_qs.filter(
            Q(username__icontains=search_query)
            | Q(first_name__icontains=search_query)
            | Q(last_name__icontains=search_query)
            | Q(staff_reg_no__icontains=search_query)
            | Q(job_title__icontains=search_query)
            | Q(department__name__icontains=search_query)
        )
    staff_qs = staff_qs.order_by("username")
    employee_count = staff_qs.count()

    paginator = Paginator(staff_qs, 10)
    page_number = request.GET.get("page")
    employees = paginator.get_page(page_number)

    current_employee = getattr(request.user, "employee", None)
    for employee in employees:
        employee.can_send_appraisal = bool(
            request.user.is_superuser
            or is_hr(request.user)
            or (current_employee and employee.supervised_by_id == current_employee.id)
        )

    return render(request, "hr/employee_list.html", {
        "employees": employees,
        "employee_count": employee_count,
        "search_query": search_query,
        "can_manage": is_hr(request.user) or is_supervisor(request.user) or request.user.is_superuser,
        "is_hr": is_hr(request.user) or request.user.is_superuser,
        "is_supervisor": is_supervisor(request.user),
    })



@login_required(login_url='login')
def delete_employee(request, pk, slug):
    employee = get_object_or_404(Employee, pk=pk, slug=slug)

    if not (request.user.is_superuser or is_supervisor(user=request.user) or is_hr(request.user)):
        messages.error(request, 'Access Denied.')
        return redirect('logout')

    if request.method == 'POST':
        employee.delete()
        messages.success(request, "Employee deleted successfully.")
        return redirect('hr:employee_list')
    return render(request, 'hr/delete_confirmation.html', {'delete': employee,
                                                           "cancel_url": reverse('hr:employee_list')})


@login_required(login_url="login")
def leave_list(request):

    user = request.user
    employee = getattr(user, "employee", None)

    # =========================================================
    # BASIC EMPLOYEE RECORD CHECK
    # =========================================================

    if employee is None:
        messages.error(
            request,
            "Your account isn't linked to an employee record yet. "
            "Please contact HR to complete your employee profile."
        )
        return redirect("hr:dashboard")


    # =========================================================
    # LEAVE VISIBILITY
    #
    # Roles are ADDITIVE.
    #
    # A user can simultaneously be:
    # - Employee
    # - Supervisor
    # - HR
    # - ED
    #
    # =========================================================

    if is_hr(user) or user.is_superuser:

        # ED can see everything.
        leaves_qs = (
            Leave.objects
            .select_related("employee", "supervisor")
            .all()
            .order_by("-applied_date")
        )

    else:

        visibility = Q()

        # -----------------------------------------------------
        # EVERY STAFF MEMBER SEES THEIR OWN LEAVE
        # -----------------------------------------------------

        visibility |= Q(employee=user)


        # -----------------------------------------------------
        # SUPERVISOR
        #
        # Also see leave applications belonging to employees
        # whose supervisor is this employee.
        # -----------------------------------------------------

        if is_supervisor(user):
            visibility |= Q(employee__supervised_by=employee)


        # -----------------------------------------------------
        # HR
        #
        # HR sees leave requests that have passed supervisor
        # approval.
        #
        # Because the user's own leave was already included
        # above, HR also sees their own applications.
        # -----------------------------------------------------

        # -----------------------------------------------------
        # BUILD QUERY
        # -----------------------------------------------------

        leaves_qs = (
            Leave.objects
            .select_related("employee", "supervisor")
            .filter(visibility)
            .distinct()
            .order_by("-applied_date")
        )


    # =========================================================
    # PAGINATION
    # =========================================================

    paginator = Paginator(leaves_qs, 5)
    page_number = request.GET.get("page")
    leaves_page = paginator.get_page(page_number)

    # ---------------------------------------------------------
    # LEAVE SCHEDULES
    # ---------------------------------------------------------

    if is_hr(user) or user.is_superuser:
        schedules = (
            LeaveSchedule.objects
            .select_related("employee", "leave_type")
            .all()
            .order_by("-start_date")
        )

    else:
        schedules = LeaveSchedule.objects.none()


    # =========================================================
    # CONTEXT
    # =========================================================

    return render(
        request,
        "hr/leave_list.html",
        {
            "leaves": leaves_page,
            "leave_schedules": schedules[:100],

            # Useful in the template
            "is_ed": is_ed(user),
            "is_hr": is_hr(user) or user.is_superuser,
            "is_supervisor": is_supervisor(user),
        }
    )


@login_required(login_url="login")
def supervisor_leave_list(request):
    """Show only leave requests assigned to the logged-in supervisor."""
    employee = getattr(request.user, "employee", None)
    if not employee or not is_supervisor(request.user):
        messages.error(request, "Only supervisors can access the supervisor leave queue.")
        return redirect("hr:leave_list")

    leaves_qs = (
        Leave.objects
        .select_related("employee", "leave_type", "supervisor")
        .filter(supervisor=employee)
        .order_by("-applied_date")
    )
    paginator = Paginator(leaves_qs, 10)
    return render(request, "hr/supervisor_leave_list.html", {
        "leaves": paginator.get_page(request.GET.get("page")),
        "supervisor": employee,
    })


@login_required(login_url="login")
def schedule_leave(request):
    if request.method == "POST":
        form = LeaveScheduleForm(request.POST)
        if form.is_valid():
            schedule = form.save(commit=False)
            schedule.employee = request.user
            schedule.save()
            messages.success(request, "Your annual leave plan has been scheduled for HR review.")
            return redirect("hr:leave_list")
    else:
        form = LeaveScheduleForm(initial={"year": date.today().year})
    return render(request, "hr/leave_schedule.html", {"form": form, "year": date.today().year})


@login_required(login_url='login')
def leave_detail(request, slug):
    leave = get_object_or_404(Leave, slug=slug)
    employee = getattr(request.user, "employee", None)
    can_view = (
        request.user.is_superuser
        or leave.employee_id == request.user.id
        or (employee and leave.supervisor_id == employee.id)
        or is_hr(request.user)
        or is_ed(request.user)
    )
    if not can_view:
        return HttpResponseForbidden("Access denied.")
    return render(request, "hr/leave_detail.html", {
        "leave": leave,
        "can_approve_supervisor": bool(request.user.is_superuser or (employee and is_supervisor(request.user) and leave.supervisor_id == employee.id)),
        "can_approve_hr": bool(request.user.is_superuser or is_hr(request.user)),
        "can_approve_ed": bool(request.user.is_superuser or is_ed(request.user)),

    })


@login_required(login_url='login')
@signature_required
def apply_leave(request):
    employment_status = getattr(request.user, "employment_status", "")
    if employment_status in {"On Leave", "Probation"}:
        messages.info(request, f"Oops!!!, Your profile is still on {employment_status}, so you can't apply now")
        return redirect('hr:leave_list')

    year = date.today().year
    leave_types = list(LeaveType.objects.all().order_by("name"))
    default_leave_type = leave_types[0] if leave_types else None
    selected_leave_type_id = (
        request.POST.get("leave_type")
        or request.GET.get("leave_type")
        or (str(default_leave_type.id) if default_leave_type else "")
    )

    balance_rows = employee_leave_balances(employee=request.user, year=year)
    leave_type_meta = {
        str(row["leave_type"].id): {
            "id": int(row["leave_type"].id),
            "name": str(row["leave_type"].name),
            "allotted_days": int(row["allotted_days"] or 0),
            "taken_days": int(row["taken_days"] or 0),
            "remaining_days": int(row["remaining_days"] or 0),
            "is_special": bool(getattr(row["leave_type"], "is_special", False)),
        }
        for row in balance_rows
    }

    selected_meta = leave_type_meta.get(str(selected_leave_type_id))
    if selected_meta is None and default_leave_type is not None:
        selected_meta = leave_type_meta.get(str(default_leave_type.id))
        selected_leave_type_id = str(default_leave_type.id)

    try:
        employee = request.user.employee

    except (Employee.DoesNotExist, AttributeError):
        messages.error(request, "You don't have an employee profile. Contact HR.")
        return redirect("hr:dashboard")

    supervisor = request.user.employee.supervised_by # if request.user.profile_type == "Staff" else intern.supervised_by
    if not supervisor:
        messages.error(request, "No supervisor assigned. Contact HR.")
        return redirect("hr:dashboard")

    if request.method == "POST":
        form = LeaveForm(request.POST)
        # Ensure model-level validation has the employee attached during form.is_valid()
        form.instance.employee = request.user
        form.instance.supervisor = supervisor

        if form.is_valid():
            leave = form.save(commit=False)
            leave.employee = request.user
            leave.supervisor = supervisor

            leave.save()
            notify(request=request, users=supervisor.user, title=f"{leave.leave_type} Leave Application",
                   message=(f"Dear {supervisor},\n\n "
                            f"A leave application has been submitted by {leave.employee}. \n\n "
                            f"Please review and take action on this application. "
                            ),category="info", source_app="hr",
                   action_url=request.build_absolute_uri(
        reverse("hr:leave_detail", kwargs={"slug": leave.slug})
                   ),)

            _send_html_email(
                subject=f"{leave.leave_type} Leave Application",
                to=[supervisor.user.email],
                template="hr/email/leave_application_notification.html",
                context={
                    "leave": leave,
                    "review_url": request.build_absolute_uri(
                       reverse("hr:leave_detail",kwargs={"slug": leave.slug},
                        )
                    ),
                },
            )
            messages.success(request, "Leave applied successfully. "
                                      "\nYou leave will be shown here once your supervisor has approve")
            return redirect("hr:leave_list")
        else:
            errors = []
            for field, field_errors in form.errors.items():
                for err in field_errors:
                    if field == "__all__":
                        errors.append(str(err))
                    else:
                        label = getattr(form.fields.get(field), "label", field)
                        errors.append(f"{label}: {err}")
            if errors:
                messages.error(request, " ".join(errors))

    else:
        form = LeaveForm(initial={"leave_type": selected_leave_type_id} if selected_leave_type_id else None)
        form.instance.employee = request.user
        form.instance.supervisor = supervisor

    return render(request, "hr/apply_leave.html", {
        "form": form,
        "year": year,
        "leave_types": leave_types,
        "selected_leave_type_id": str(selected_leave_type_id or ""),
        "selected_leave_type_name": (selected_meta or {}).get("name", ""),
        "selected_allotted_days": int((selected_meta or {}).get("allotted_days", 0) or 0),
        "selected_taken_days": int((selected_meta or {}).get("taken_days", 0) or 0),
        "selected_remaining_days": int((selected_meta or {}).get("remaining_days", 0) or 0),
        "leave_type_meta": leave_type_meta,
    })


@login_required(login_url='login')
@signature_required
@user_passes_test(is_supervisor)
def approve_supervisor(request, slug, action):
    leave = get_object_or_404(Leave, slug=slug)

    assigned_employee = getattr(request.user, "employee", None)
    if not request.user.is_superuser and (
        not assigned_employee or leave.supervisor_id != assigned_employee.id
    ):
        messages.error(request, "Only the assigned supervisor can action this leave request.")
        return redirect(reverse("hr:leave_detail", kwargs={"slug": leave.slug}))

    if action in {"approved", "denied"} and leave_signer_conflict(
        requester=leave.employee,
        # ``leave.supervisor`` is assigned when the request is created; it is
        # not a signature until the supervisor approval flag is set.
        previous_signers=[
            leave.hr if leave.hr_approved else None,
            leave.ed if leave.ed_approved else None,
        ],
    ):
        return redirect(reverse("hr:leave_detail", kwargs={"slug": leave.slug}))

    if request.method == "POST":

        if action == "approved":
            leave.supervisor = request.user.employee
            leave.supervisor_approved = True
            leave.supervisor_approved_at = timezone.now()

        elif action == "denied":
            leave.status = "Denied"
            leave.employee.status = "Active"
            leave.employee.save(update_fields=["status"])
            leave.save(update_fields=["status"])
            _notify_leave_recipients(
                request=request,
                leave=leave,
                recipients=[leave.employee],
                title="Leave request denied by supervisor",
                message=(
                    f"Your {leave.leave_type} leave request for {leave.start_date} "
                    f"to {leave.end_date} was denied by your supervisor."
                ),
                category="error",
            )
            messages.error(request, "Leave rejected.")
            return redirect(reverse("hr:leave_detail", kwargs={"slug": leave.slug}))

        elif action == "reverse":
            leave.supervisor_approved = False

        else:
            messages.warning(request, "Invalid action.")
            return redirect(reverse("hr:leave_detail", kwargs={"slug": leave.slug}))

        leave.update_status()
        leave.save()
        if action == "approved":
            _notify_leave_recipients(
                request=request,
                leave=leave,
                recipients=Profile.objects.filter(
                    groups__name="HR", is_active=True
                ).distinct(),
                title="Leave request approved by supervisor",
                message=(
                    f"{leave.employee}'s {leave.leave_type} leave request for "
                    f"{leave.start_date} to {leave.end_date} was approved by the "
                    "supervisor and is awaiting HR review."
                ),
                category="info",
            )
        messages.success(request, "Supervisor action recorded.")
        return redirect(reverse("hr:leave_detail", kwargs={"slug": leave.slug}))

    return render(request, "hr/confirm_action.html", {"obj": leave, "action": action})


@login_required(login_url='login')
@signature_required
@user_passes_test(is_hr)
def approve_hr(request, slug, action):
    leave = get_object_or_404(Leave, slug=slug)

    if action in {"approved", "denied"} and leave_signer_conflict(
        requester=leave.employee, previous_signers=
            [leave.supervisor if leave.supervisor_approved else None,
             leave.ed if leave.ed_approved else None,],):
        return redirect(reverse("hr:leave_detail", kwargs={"slug": leave.slug}))

    if request.method == "POST":
        leave.hr = request.user

        if action == "approved":
            leave.hr_approved = True
            leave.hr_approved_at = timezone.now()

        elif action == "denied":
            leave.status = "Denied"
            leave.employee.status = "Active"
            leave.employee.save(update_fields=["status"])
            leave.save(update_fields=["status"])
            _notify_leave_recipients(
                request=request,
                leave=leave,
                recipients=[leave.employee, leave.supervisor.user if leave.supervisor else None],
                title="Leave request denied by HR",
                message=(
                    f"{leave.employee}'s {leave.leave_type} leave request for "
                    f"{leave.start_date} to {leave.end_date} was denied by HR."
                ),
                category="error",
            )
            messages.error(request, "Leave rejected.")
            return redirect(reverse("hr:leave_detail", kwargs={"slug": leave.slug}))

        elif action == "reverse":
            if leave.ed_approved:
                messages.error(request, "Cannot reverse after ED approval.")
                return redirect(reverse("hr:leave_detail", kwargs={"slug": leave.slug}))

            leave.hr_approved = False

        leave.update_status()
        leave.save()
        if action == "approved":
            _notify_leave_recipients(
                request=request,
                leave=leave,
                recipients=Profile.objects.filter(
                    groups__name="ED", is_active=True
                ).distinct(),
                title="Leave request approved by HR",
                message=(
                    f"{leave.employee}'s {leave.leave_type} leave request for "
                    f"{leave.start_date} to {leave.end_date} was approved by HR "
                    "and is awaiting ED review."
                ),
                category="info",
            )
        messages.success(request, "HR action recorded.")
        return redirect(reverse("hr:leave_detail", kwargs={"slug": leave.slug}))

    return render(request, "hr/confirm_action.html", {"obj": leave, "action": action})


@login_required(login_url='login')
@signature_required
@user_passes_test(is_ed)
def approve_ed(request, slug, action):
    leave = get_object_or_404(Leave, slug=slug)

    if action in {"approved", "denied"} and leave_signer_conflict(
        requester=leave.employee,
        previous_signers=[
            leave.supervisor if leave.supervisor_approved else None,
            leave.hr if leave.hr_approved else None,
        ],
    ):
        return redirect(reverse("hr:leave_detail", kwargs={"slug": leave.slug}))

    if request.method == "POST":
        leave.ed = request.user

        if action == "approved":
            leave.ed_approved = True
            leave.employee.status = "On Leave"
            leave.ed_approved_at = timezone.now()
            leave.employee.save(update_fields=["status"])

        elif action == "denied":
            leave.status = "Denied"
            leave.employee.status = "Active"
            leave.employee.save(update_fields=["status"])
            leave.save(update_fields=["status"])
            _notify_leave_recipients(
                request=request,
                leave=leave,
                recipients=[leave.employee],
                title="Leave request denied by ED",
                message=(
                    f"Your {leave.leave_type} leave request for {leave.start_date} "
                    f"to {leave.end_date} was denied by the Executive Director."
                ),
                category="error",
            )
            messages.error(request, "Leave rejected.")
            return redirect(reverse("hr:leave_detail", kwargs={"slug": leave.slug}))

        elif action == "reverse":
            if leave.ed_approved:
                messages.error(request, "Already finalized. Cannot reverse.")
                return redirect(reverse("hr:leave_detail", kwargs={"slug": leave.slug}))

            leave.ed_approved = False

        leave.update_status()
        leave.save()
        if action == "approved":
            _notify_leave_recipients(
                request=request,
                leave=leave,
                recipients=[leave.employee],
                title="Leave request fully approved",
                message=(
                    f"Your {leave.leave_type} leave request for {leave.start_date} "
                    f"to {leave.end_date} has been fully approved by the "
                    "Executive Director."
                ),
                category="success",
            )
        messages.success(request, "ED action recorded.")
        return redirect(reverse("hr:leave_detail", kwargs={"slug": leave.slug}))

    return render(request, "hr/confirm_action.html", {"obj": leave, "action": action})


@login_required(login_url='login')
def delete_leave(request, slug):
    if not (is_supervisor(user=request.user) or is_hr(request.user)):
        messages.error(request, 'Access Denied.')
        return redirect('logout')

    leave = get_object_or_404(Leave, slug=slug)
    if request.method == 'POST':
        leave.delete()
        messages.success(request, "Leave deleted successfully.")
        return redirect('hr:leave_list')
    return render(request, 'hr/delete_confirmation.html', {'delete': leave,
                                                           "cancel_url": reverse('hr:leave_list')})



@login_required(login_url="login")
def leave_yearly_report(request):
    if not (is_supervisor(request.user) or is_hr(request.user) or is_ed(request.user) or request.user.is_superuser):
        return HttpResponseForbidden("Access denied.")

    year = int(request.GET.get("year", date.today().year))
    start_date = parse_date(request.GET.get("start_date") or "")
    end_date = parse_date(request.GET.get("end_date") or "")

    leave_types = list(LeaveType.objects.all().order_by("name"))
    default_leave_type = leave_types[0] if leave_types else None
    leave_type_id = request.GET.get("leave_type") or (str(default_leave_type.id) if default_leave_type else "")
    selected_leave_type = next((lt for lt in leave_types if str(lt.id) == str(leave_type_id)), default_leave_type)

    report_rows = yearly_leave_allocation_report(year=year, start_date=start_date, end_date=end_date)
    staff_rows = (
        staff_leave_balance_report(
            year=year,
            leave_type=selected_leave_type,
            start_date=start_date,
            end_date=end_date,
            include_zero=True,
        )
        if selected_leave_type
        else []
    )

    # Organization totals (leave type summary)
    total_staff = report_rows[0]["staff_count"] if report_rows else 0
    total_allotted = sum(r["allotted_total_days"] for r in report_rows)
    total_approved = sum(r["approved_total_days"] for r in report_rows)
    total_remaining = sum(r["remaining_total_days"] for r in report_rows)

    # Staff totals (selected leave type)
    staff_count = len(staff_rows)
    staff_allotted_per = int(getattr(selected_leave_type, "no_of_days", 0) or 0) if selected_leave_type else 0
    staff_total_allotted = staff_count * staff_allotted_per
    staff_total_taken = sum(int(r.get("taken_days") or 0) for r in staff_rows)
    staff_total_remaining = max(0, staff_total_allotted - staff_total_taken)

    leave_chart_labels = [str(row["leave_type"]) for row in report_rows]
    leave_chart_used = [int(row["approved_total_days"] or 0) for row in report_rows]
    leave_chart_remaining = [int(row["remaining_total_days"] or 0) for row in report_rows]
    leave_usage_percentages = [
        round((used / allotted) * 100, 1) if allotted else 0
        for used, allotted in zip(
            leave_chart_used,
            [int(row["allotted_total_days"] or 0) for row in report_rows],
        )
    ]

    context = {
        "year": year,
        "start_date": request.GET.get("start_date") or "",
        "end_date": request.GET.get("end_date") or "",

        # org summary
        "report_rows": report_rows,
        "total_staff": total_staff,
        "total_allotted": total_allotted,
        "total_approved": total_approved,
        "total_remaining": total_remaining,

        # staff summary
        "leave_types": leave_types,
        "selected_leave_type": selected_leave_type,
        "staff_rows": staff_rows,
        "staff_total_allotted": staff_total_allotted,
        "staff_total_taken": staff_total_taken,
        "staff_total_remaining": staff_total_remaining,
        "leave_chart_labels": leave_chart_labels,
        "leave_chart_used": leave_chart_used,
        "leave_chart_remaining": leave_chart_remaining,
        "leave_usage_percentages": leave_usage_percentages,
    }

    return render(request, "hr/leave_report.html", context)


@login_required(login_url="login")
def leave_yearly_report_pdf(request):
    if not (is_supervisor(request.user) or is_hr(request.user) or is_ed(request.user) or request.user.is_superuser):
        return HttpResponseForbidden("Access denied.")

    year = int(request.GET.get("year", date.today().year))
    start_date = parse_date(request.GET.get("start_date") or "")
    end_date = parse_date(request.GET.get("end_date") or "")

    report_rows = yearly_leave_allocation_report(year=year, start_date=start_date, end_date=end_date)

    total_staff = report_rows[0]["staff_count"] if report_rows else 0
    total_allotted = sum(r["allotted_total_days"] for r in report_rows)
    total_approved = sum(r["approved_total_days"] for r in report_rows)
    total_remaining = sum(r["remaining_total_days"] for r in report_rows)

    context = {
        "year": year,
        "start_date": request.GET.get("start_date") or "",
        "end_date": request.GET.get("end_date") or "",
        "report_rows": report_rows,
        "total_staff": total_staff,
        "total_allotted": total_allotted,
        "total_approved": total_approved,
        "total_remaining": total_remaining,
    }

    return render_to_pdf("hr/leave_report_pdf.html", context)


@login_required(login_url="login")
def export_leave_report_excel(request):
    if not (is_supervisor(request.user) or is_hr(request.user) or is_ed(request.user) or request.user.is_superuser):
        return HttpResponseForbidden("Access denied.")

    year = int(request.GET.get("year", date.today().year))
    start_date = parse_date(request.GET.get("start_date") or "")
    end_date = parse_date(request.GET.get("end_date") or "")

    report_rows = yearly_leave_allocation_report(year=year, start_date=start_date, end_date=end_date)

    wb = Workbook()
    ws = wb.active
    ws.title = "Leave Summary"

    ws.merge_cells("A1:E1")
    ws["A1"] = "Leave Allocation Summary"
    ws["A1"].font = Font(bold=True, size=14, color="228B22")
    ws["A1"].alignment = Alignment(horizontal="center")

    ws.merge_cells("A2:E2")
    range_label = f"{year}"
    if request.GET.get("start_date") and request.GET.get("end_date"):
        range_label = f"{year} ({request.GET.get('start_date')} to {request.GET.get('end_date')})"
    ws["A2"] = range_label
    ws["A2"].alignment = Alignment(horizontal="center")
    ws["A2"].font = Font(italic=True, size=10)

    headers = ["Leave Type", "Staff Count", "Allotted (Total)", "Taken/Approved", "Remaining (Total)"]
    ws.append(headers)
    for col, _ in enumerate(headers, start=1):
        cell = ws.cell(row=3, column=col)
        cell.font = Font(bold=True, color="228B22")
        cell.alignment = Alignment(horizontal="center")

    for row in report_rows:
        ws.append(
            [
                row["leave_type"].name,
                int(row["staff_count"] or 0),
                int(row["allotted_total_days"] or 0),
                int(row["approved_total_days"] or 0),
                int(row["remaining_total_days"] or 0),
            ]
        )

    total_staff = report_rows[0]["staff_count"] if report_rows else 0
    total_allotted = sum(r["allotted_total_days"] for r in report_rows)
    total_approved = sum(r["approved_total_days"] for r in report_rows)
    total_remaining = sum(r["remaining_total_days"] for r in report_rows)

    ws.append([])
    ws.append(["TOTAL", total_staff, total_allotted, total_approved, total_remaining])
    ws.cell(row=ws.max_row, column=1).font = Font(bold=True)

    response = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="leave_report_{year}.xlsx"'
    wb.save(response)
    return response


@login_required(login_url="login")
def export_leave_staff_excel(request):
    if not (is_supervisor(request.user) or is_hr(request.user) or is_ed(request.user) or request.user.is_superuser):
        return HttpResponseForbidden("Access denied.")

    year = int(request.GET.get("year", date.today().year))
    start_date = parse_date(request.GET.get("start_date") or "")
    end_date = parse_date(request.GET.get("end_date") or "")

    leave_types = list(LeaveType.objects.all().order_by("name"))
    default_leave_type = leave_types[0] if leave_types else None
    leave_type_id = request.GET.get("leave_type") or (str(default_leave_type.id) if default_leave_type else "")
    selected_leave_type = next((lt for lt in leave_types if str(lt.id) == str(leave_type_id)), default_leave_type)
    if not selected_leave_type:
        return HttpResponse("No leave types configured.", status=400)

    staff_rows = staff_leave_balance_report(
        year=year,
        leave_type=selected_leave_type,
        start_date=start_date,
        end_date=end_date,
        include_zero=True,
    )

    wb = Workbook()
    ws = wb.active
    ws.title = "Staff Balances"

    ws.merge_cells("A1:D1")
    ws["A1"] = "Staff Leave Balances"
    ws["A1"].font = Font(bold=True, size=14, color="228B22")
    ws["A1"].alignment = Alignment(horizontal="center")

    ws.merge_cells("A2:D2")
    range_label = f"{year} - {selected_leave_type.name}"
    if request.GET.get("start_date") and request.GET.get("end_date"):
        range_label = f"{year} - {selected_leave_type.name} ({request.GET.get('start_date')} to {request.GET.get('end_date')})"
    ws["A2"] = range_label
    ws["A2"].alignment = Alignment(horizontal="center")
    ws["A2"].font = Font(italic=True, size=10)

    headers = ["Employee", "Allotted", "Taken", "Remaining"]
    ws.append(headers)
    for col, _ in enumerate(headers, start=1):
        cell = ws.cell(row=3, column=col)
        cell.font = Font(bold=True, color="228B22")
        cell.alignment = Alignment(horizontal="center")

    for row in staff_rows:
        ws.append(
            [
                str(row["employee"]),
                int(row["allotted_days"] or 0),
                int(row["taken_days"] or 0),
                int(row["remaining_days"] or 0),
            ]
        )

    staff_count = len(staff_rows)
    allotted_per_staff = int(getattr(selected_leave_type, "no_of_days", 0) or 0)
    total_allotted = staff_count * allotted_per_staff
    total_taken = sum(int(r.get("taken_days") or 0) for r in staff_rows)
    total_remaining = max(0, total_allotted - total_taken)

    ws.append([])
    ws.append(["TOTAL", total_allotted, total_taken, total_remaining])
    ws.cell(row=ws.max_row, column=1).font = Font(bold=True)

    response = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    safe_name = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in selected_leave_type.name)
    response["Content-Disposition"] = f'attachment; filename="leave_staff_{safe_name}_{year}.xlsx"'
    wb.save(response)
    return response


@login_required(login_url='login')
def attendance_list(request):
    employee = request.user
    # HR, ED and superusers see all records. Supervisors see their own
    # records plus records belonging to their direct supervisees.
    if is_hr(request.user) or request.user.is_superuser:
        record_qs = Attendance.objects.all().order_by("-date")
    elif is_supervisor(request.user):
        record_qs = Attendance.objects.filter(
            Q(employee=employee) | Q(employee__supervised_by=employee)
        ).distinct().order_by("-date")
    else:
        record_qs = Attendance.objects.filter(employee=employee).order_by("-date")
    # record_qs = Attendance.objects.all()
    paginator = Paginator(record_qs, 5)  # 10 employees per page
    page_number = request.GET.get('page')
    records = paginator.get_page(page_number)
    return render(request, 'hr/attendance_list.html', {'records': records})


@login_required(login_url='login')
def mark_attendance(request):
    if not (is_supervisor(request.user) or is_hr(request.user)):
        return HttpResponseForbidden("Access denied.")

    if request.method == 'POST':
        form = AttendanceForm(request.POST)
        if form.is_valid():

            employee = form.cleaned_data['employee']
            today = now().date()
            if Attendance.objects.filter(employee=employee, date__date=today).exists():
                messages.warning(request, f"You have already marked attendance today for {employee}.")
                return redirect("hr:attendance_list")

            form.save()
            messages.success(request, f"You have successfully marked attendance today for {employee}.")
            return redirect('hr:attendance_list')
    else:
        form = AttendanceForm()
    return render(request, 'hr/hr_mark_staff_attendance.html', {'form': form})


@login_required(login_url='login')
def _legacy_staff_mark_attendance(request):
    employee = request.user
    today = now().date()

    # # Prevent double marking
    if Attendance.objects.filter(employee=employee, date__date=today).exists():
        messages.warning(request, "⚠️ Already marked attendance today.")
        return redirect("hr:attendance_list")

    if request.method == "POST":
        # Get device hash directly from POST
        device_hash = request.POST.get("device_hash")
        form = StaffAttendanceForm(request.POST)
        if form.is_valid():
            # Bind device hash first time
            if not employee.device_hash:
                employee.device_hash = device_hash
                employee.save()
                messages.info(request, "📌 Your account has been bound to this device.")

            # Enforce same device
            if employee.device_hash and employee.device_hash != device_hash:
                messages.error(request, "❌ This account is already bound to another device. Contact admin.")
                return redirect("hr:attendance_list")

            # Save attendance (only employee + date + status)
            attendance = form.save(commit=False)
            attendance.employee = employee
            attendance.date = today
            attendance.save()

            messages.success(request, "✅ Attendance marked successfully!")
            return redirect("hr:attendance_list")
        else:
            messages.error(request, "❌ Failed to mark attendance. Please try again.")
    else:
        form = StaffAttendanceForm()

    return render(request, "hr/staff_mark_attendance.html", {"form": form})


@login_required(login_url='login')
def staff_mark_attendance(request):
    employee = request.user
    today = now().date()

    if Attendance.objects.filter(employee=employee, date__date=today).exists():
        messages.warning(request, "You have already marked attendance today.")
        return redirect("hr:attendance_list")

    if request.method == "POST":
        device_token = (request.POST.get("device_token") or "").strip()
        user_agent = request.META.get("HTTP_USER_AGENT", "")
        device_hash = StaffDevice.generate_hash(device_token, user_agent) if device_token else ""
        form = StaffAttendanceForm(request.POST)

        if form.is_valid():
            latitude = form.cleaned_data.get("latitude")
            longitude = form.cleaned_data.get("longitude")
            if latitude is None or longitude is None:
                messages.error(request, "Your current location could not be captured. Allow location access and try again.")
                return render(request, "hr/staff_mark_attendance.html", {
                    "form": form,
                    "device_bound": StaffDevice.objects.filter(staff=employee).exists(),
                })

            if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                messages.error(request, "The captured location is invalid. Please try again.")
                return render(request, "hr/staff_mark_attendance.html", {
                    "form": form,
                    "device_bound": StaffDevice.objects.filter(staff=employee).exists(),
                })

            if not device_hash:
                messages.error(request, "This browser could not identify the device. Enable browser storage and try again.")
                return render(request, "hr/staff_mark_attendance.html", {
                    "form": form,
                    "device_bound": StaffDevice.objects.filter(staff=employee).exists(),
                })

            bound_device = StaffDevice.objects.filter(staff=employee).order_by("created_at").first()
            device_used_by_other_staff = StaffDevice.objects.filter(
                device_hash=device_hash
            ).exclude(staff=employee).exists()

            if device_used_by_other_staff:
                messages.error(request, "This device is already bound to another staff account. Contact HR if you need assistance.")
                return redirect("hr:attendance_list")

            if bound_device and bound_device.device_hash != device_hash:
                messages.error(request, "Your account is bound to another device or browser. Contact HR to change it.")
                return redirect("hr:attendance_list")

            if not bound_device:
                StaffDevice.objects.create(
                    staff=employee,
                    device_hash=device_hash,
                    ip_address=request.META.get("REMOTE_ADDR") or "0.0.0.0",
                    user_agent=user_agent,
                    approved=True,
                )
                messages.info(request, "Your account is now bound to this device and browser for attendance. Contact HR if you need to change it.")

            attendance = form.save(commit=False)
            attendance.employee = employee
            attendance.date = today
            attendance.save()
            messages.success(request, "Attendance marked successfully.")
            return redirect("hr:attendance_list")

        messages.error(request, "Attendance could not be recorded. Capture your location and try again.")
    else:
        form = StaffAttendanceForm(initial={"status": "Present"})

    return render(request, "hr/staff_mark_attendance.html", {
        "form": form,
        "device_bound": StaffDevice.objects.filter(staff=employee).exists(),
    })


@login_required(login_url='login')
def export_attendance_pdf(request):
    start_date = request.GET.get("start_date")
    end_date = request.GET.get("end_date")
    export_all = request.GET.get("export_all")

    user = request.user

    if user.is_superuser:
        attendances = Attendance.objects.all().order_by("date")
        if not export_all and start_date and end_date:
            start_date = parse_date(start_date)
            end_date = parse_date(end_date)
            if start_date and end_date:
                attendances = attendances.filter(date__range=(start_date, end_date))
    else:
        # Regular employee - only their own records
        attendances = Attendance.objects.filter(employee=user).order_by("date")
        if start_date and end_date:
            start_date = parse_date(start_date)
            end_date = parse_date(end_date)
            if start_date and end_date:
                attendances = attendances.filter(date__range=(start_date, end_date))

    # --- PDF generation code remains unchanged below ---
    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="attendance_report.pdf"'

    p = canvas.Canvas(response, pagesize=A4)
    width, height = A4

    # --- Header Section ---
    p.setFont("Helvetica-Bold", 18)
    p.setFillColor(colors.HexColor("#3b2938"))
    p.drawString(220, height - 50, "DDS-NK THRIVE")
    p.setFont("Helvetica", 12)
    p.drawString(240, height - 70, "Attendance Report")

    if not export_all and start_date and end_date:
        p.setFont("Helvetica-Oblique", 10)
        p.setFillColor(colors.black)
        p.drawString(220, height - 85, f"From {start_date} to {end_date}")
    else:
        p.setFont("Helvetica-Oblique", 10)
        p.setFillColor(colors.black)
        p.drawString(260, height - 85, "All Records")

    # --- Table Section ---
    y = height - 140
    row_height = 20

    # Table headers in green
    p.setFont("Helvetica-Bold", 11)
    p.setFillColor(colors.green)
    p.drawString(50, y, "Employee")
    p.drawString(250, y, "Date")
    p.drawString(400, y, "Status")
    y -= row_height
    p.setFont("Helvetica", 10)
    p.setFillColor(colors.black)

    total_present = 0
    total_absent = 0
    total_leave = 0

    for index, att in enumerate(attendances, start=1):
        # Alternate background
        if index % 2 == 0:
            p.setFillColorRGB(0.95, 0.95, 0.95)
            p.rect(45, y - 5, width - 90, row_height, stroke=0, fill=1)
            p.setFillColor(colors.black)

        # Draw row
        p.drawString(50, y, att.employee.get_full_name())
        p.drawString(250, y, att.date.strftime("%Y-%m-%d  %H:%M:%S"))
        p.drawString(400, y, att.status)

        # Count summary
        if att.status.lower() == "present":
            total_present += 1
        elif att.status.lower() == "absent":
            total_absent += 1
        elif att.status.lower() == "leave":
            total_leave += 1

        y -= row_height
        if y < 50:
            p.showPage()
            y = height - 50

    # --- Summary Row ---
    y -= 20
    p.setFont("Helvetica-Bold", 11)
    p.setFillColor(colors.green)
    p.drawString(50, y, "Summary")
    p.setFillColor(colors.black)
    p.setFont("Helvetica", 10)
    p.drawString(150, y, f"Present: {total_present}")
    p.drawString(300, y, f"Absent: {total_absent}")
    p.drawString(450, y, f"Leave: {total_leave}")

    p.save()
    return response


@login_required(login_url='login')
def export_attendance_excel(request):
    start_date = request.GET.get("start_date")
    end_date = request.GET.get("end_date")
    export_all = request.GET.get("export_all")

    user = request.user

    if user.is_superuser:
        attendances = Attendance.objects.all().order_by("date")
        if not export_all and start_date and end_date:
            start_date = parse_date(start_date)
            end_date = parse_date(end_date)
            if start_date and end_date:
                attendances = attendances.filter(date__range=(start_date, end_date))
    else:
        attendances = Attendance.objects.filter(employee=user.employee).order_by("date")
        if start_date and end_date:
            start_date = parse_date(start_date)
            end_date = parse_date(end_date)
            if start_date and end_date:
                attendances = attendances.filter(date__range=(start_date, end_date))

    # --- Excel generation code remains unchanged below ---
    wb = Workbook()
    ws = wb.active
    ws.title = "Attendance"

    # --- Header ---
    ws.merge_cells("A1:C1")
    ws["A1"] = "DDS-NK THRIVE - Attendance Report"
    ws["A1"].font = Font(bold=True, color="228B22", size=14)
    ws["A1"].alignment = Alignment(horizontal="center")

    if not export_all and start_date and end_date:
        ws.merge_cells("A2:C2")
        ws["A2"] = f"From {start_date} to {end_date}"
    else:
        ws.merge_cells("A2:C2")
        ws["A2"] = "All Records"

    ws["A2"].alignment = Alignment(horizontal="center")
    ws["A2"].font = Font(italic=True, size=10)

    # Column headers
    headers = ["Employee", "Date", "Status"]
    ws.append(headers)

    for col, header in enumerate(headers, start=1):
        cell = ws.cell(row=3, column=col)
        cell.font = Font(bold=True, color="228B22")  # green text
        cell.alignment = Alignment(horizontal="center")

    # Data rows
    total_present = 0
    total_absent = 0
    total_leave = 0

    for att in attendances:
        ws.append([
            att.employee.get_full_name(),
            att.date.strftime("%Y-%m-%d"),
            att.status
        ])

        if att.status.lower() == "present":
            total_present += 1
        elif att.status.lower() == "absent":
            total_absent += 1
        elif att.status.lower() == "leave":
            total_leave += 1

    # Summary row
    last_row = ws.max_row + 2
    ws[f"A{last_row}"] = "Summary"
    ws[f"A{last_row}"].font = Font(bold=True, color="228B22")
    ws[f"B{last_row}"] = f"Present: {total_present}"
    ws[f"C{last_row}"] = f"Absent: {total_absent} | Leave: {total_leave}"

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response['Content-Disposition'] = 'attachment; filename="attendance_report.xlsx"'
    wb.save(response)
    return response



@login_required(login_url='login')
def training_list(request):
    trainings_qs = Training.objects.all().order_by('-start_date')
    paginator = Paginator(trainings_qs, 4)  # 10 employees per page
    page_number = request.GET.get('page')
    trainings = paginator.get_page(page_number)
    return render(request, 'hr/training_list.html', {'trainings': trainings})


class TrainingDetailModalView(LoginRequiredMixin, DetailView):
    model = Training
    slug_field = "slug"
    slug_url_kwarg = "slug"
    template_name = "hr/training_detail_modal.html"
    context_object_name = "training"

    def get_queryset(self):
        return (
            Training.objects
            .prefetch_related("participants", "participants__department")
        )

    def render_to_response(self, context, **response_kwargs):
        # Only allow AJAX access
        if not self.request.headers.get("x-requested-with") == "XMLHttpRequest":
            return HttpResponseForbidden("Invalid request")
        return super().render_to_response(context, **response_kwargs)


@login_required(login_url='login')
def add_training(request):
    if not is_supervisor(user=request.user):
        messages.error(request, 'Access Denied.')
        return redirect('logout')

    if request.method == 'POST':
        form = TrainingForm(request.POST)
        if form.is_valid():
            form.save()
            participants = form.cleaned_data['participants']
            start_date = form.cleaned_data['start_date']
            description = form.cleaned_data['description']
            title = form.cleaned_data['title']
            for employee in participants:
                notify(
                    title=title,
                    message=f'You are invited for a training commencing on {start_date}. {description}',
                    users=employee,
                    action_url=""
                )
                send_mail(subject=title, message=description, from_email=settings.EMAIL_HOST_USER,
                          recipient_list=[employee.email], fail_silently=False)
            return redirect('hr:training_list')
    else:
        form = TrainingForm()
    return render(request, 'hr/add_training.html', {'form': form})


class TrainingUpdateView(LoginRequiredMixin, UserPassesTestMixin, UpdateView):
    model = Training
    slug_field = "slug"
    slug_url_kwarg = "slug"
    form_class = TrainingForm
    template_name = "hr/training_edit.html"
    context_object_name = "training"

    def get_queryset(self):
        return Training.objects.prefetch_related("participants")

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        if obj.slug != self.kwargs.get("slug"):
            from django.http import Http404
            raise Http404("Invalid URL")
        return obj

    def test_func(self):
        return self.request.user.is_staff or is_hr(self.request.user)

    def form_valid(self, form):
        participants = form.cleaned_data['participants']
        start_date = form.cleaned_data['start_date']
        end_date = form.cleaned_data['end_date']
        description = form.cleaned_data['description']
        title = form.cleaned_data['title']
        if end_date < start_date:
            form.add_error("end_date", "End date cannot be before start date.")
            return self.form_invalid(form)

        for employee in participants:
            notify(
                title=title,
                message=f'You are invited for a training commencing on {start_date}. {description}',
                users=employee,
                action_url=""
            )
            send_mail(subject=title, message=description, from_email=settings.EMAIL_HOST_USER,
                      recipient_list=[employee.email], fail_silently=False)

        messages.success(self.request, f"Training ({form.cleaned_data['title']}) updated successfully.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy("hr:training_list")


@login_required(login_url='login')
def trash_training(request, slug):
    training = get_object_or_404(Training, slug=slug)

    if not (is_supervisor(user=request.user) or is_hr(request.user)):
        messages.error(request, 'Access Denied.')
        return redirect('logout')

    if request.method == 'POST':
        messages.success(request, f"Training with ({training.title}) deleted successfully.")
        training.delete()
        return redirect('hr:training_list')
    return render(request, 'hr/delete_confirmation.html', {'delete': training,
                                                           "cancel_url": reverse('hr:training_list')})


@login_required(login_url='login')
def sitrep_list(request):
    sitrep_qs = SituationReport.objects.all().order_by("-created_at")
    paginator = Paginator(sitrep_qs, 5)  # 5 per page
    page_number = request.GET.get("page")
    reports = paginator.get_page(page_number)
    return render(request, "sitrep/sitrep_list.html", {"reports": reports})


@login_required(login_url='login')
def create_sitrep(request):
    if request.method == "POST":
        form = SituationReportForm(request.POST, request.FILES)
        if form.is_valid():
            sitrep = form.save(commit=False)
            sitrep.reporter = request.user
            sitrep.save()

            # Supervisors to notify
            supervisors = Profile.objects.filter(is_staff=True, is_superuser=True).values_list("email", flat=True)
            if supervisors:
                context = {
                    "reporter": request.user.get_full_name(),
                    "title": sitrep.title,
                    "description": sitrep.description,
                    "status": sitrep.status,
                    "url": request.build_absolute_uri(f"/sitrep/{sitrep.id}/"),
                    "year": datetime.now().year,
                }
                html_content = render_to_string("sitrep/email.html", context)
                text_content = strip_tags(html_content)

                email = EmailMultiAlternatives(
                    subject=f"🚨 New Situation Report: {sitrep.title}",
                    body=text_content,
                    from_email=f"{settings.EMAIL_HOST_USER}",
                    to=[f"{settings.EMAIL_HOST_USER}"],
                )
                email.attach_alternative(html_content, "text/html")
                email.send()

            # ✅ Create in-app notification
            notify(
                title=f"Situation Report '{sitrep.title}' submitted",
                message=f"Your Situation Report '{sitrep.title}' has been submitted.",
                users=request.user,
                action_url=""
            )

            messages.success(request, "✅ Situation Report submitted successfully.")
            return redirect("hr:sitrep_list")
    else:
        form = SituationReportForm()
    return render(request, "sitrep/create_sitrep.html", {"form": form})


@login_required(login_url='login')
def sitrep_detail(request, pk):
    report = get_object_or_404(SituationReport, pk=pk)
    # Admin/supervisor status update
    if is_supervisor(request.user) and request.method == "POST":
        form = UpdateSitrepStatusForm(request.POST, instance=report)
        if form.is_valid():
            form.save()
            messages.success(request, "✅ Report status updated.")
            return redirect("hr:sitrep_detail", pk=pk)
    else:
        form = UpdateSitrepStatusForm(instance=report) if is_supervisor(request.user) else None

    return render(request, "sitrep/sitrep_detail.html", {"report": report, "form": form})
