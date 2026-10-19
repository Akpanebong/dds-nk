from .utils import notify, _send_html_email
from .orientation_models import OrientationPlan, OrientationSession, OrientationPlanStatus, OrientationSessionStatus
from .views import is_hr, is_cmt, is_department_head
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from core.models import StaffProfile as Profile
from django.db.models import Prefetch
from django.contrib import messages
from .forms import OrientationPlanCreateForm, OrientationSessionScheduleForm, OrientationSessionCompleteForm
from django.db import transaction
from datetime import datetime



def _orientation_plan_url(request, plan: OrientationPlan) -> str:
    if is_hr(request.user) or request.user.is_superuser:
        return request.build_absolute_uri(reverse("hr:orientation_hr_detail", args=[plan.id]))
    if is_cmt(request.user):
        return request.build_absolute_uri(reverse("hr:orientation_cmt_detail", args=[plan.id]))
    return request.build_absolute_uri(reverse("hr:orientation_my"))


@login_required(login_url="login")
def orientation_hr_list(request):

    if not (is_hr(request.user) or request.user.is_superuser or is_department_head(request.user)):
        messages.info(request, "Access denied.")
        return redirect('hr:orientation_my')

    probation_staff = (
        Profile.objects.filter(is_active=True, status="Probation")
        .select_related("department")
        .order_by("last_name", "first_name", "username")
    )

    plans = (
        OrientationPlan.objects.select_related("staff", "staff__department")
        .prefetch_related("sessions", "sessions__department")
        .order_by("-created_at")
    )

    plan_by_staff_id = {p.staff_id: p for p in plans}
    staff_rows = [(s, plan_by_staff_id.get(s.id)) for s in probation_staff]

    return render(request, "orientation/hr_list.html", {"staff_rows": staff_rows})


@login_required(login_url="login")
def orientation_hr_create(request, staff_slug):
    created_by = request.user
    if not (is_hr(request.user) or request.user.is_superuser):
        messages.info(request, "Access denied.")
        return redirect('hr:orientation_my')

    staff = get_object_or_404(Profile, slug=staff_slug, is_active=True)
    existing = getattr(staff, "orientation_plan", None)
    if existing and existing.status != OrientationPlanStatus.CANCELED:
        messages.info(request, "Orientation plan already exists for this staff.")
        return redirect("hr:orientation_hr_detail", plan_id=existing.id)

    if request.method == "POST":
        form = OrientationPlanCreateForm(request.POST)
        if form.is_valid():
            departments = list(form.cleaned_data["departments"])
            missing_heads = [d.name for d in departments if not d.head]
            if missing_heads:
                form.add_error(
                    "departments",
                    f"Department head not set for: {', '.join(missing_heads)}. Please set heads first.",
                )
            else:
                with transaction.atomic():
                    plan = OrientationPlan.objects.create(
                        staff=staff, created_by=request.user, notes=form.cleaned_data.get("notes", "")
                    )
                    sessions = []
                    for department in departments:
                        sessions.append(
                            OrientationSession(
                                plan=plan,
                                department=department,
                            )
                        )
                    OrientationSession.objects.bulk_create(sessions)

                # Notify unit heads (in-app + email).
                for session in plan.sessions.select_related("department", "department__head").all():
                    head = session.department.head
                    if not head:
                        continue
                    url = request.build_absolute_uri(reverse("hr:orientation_head_session_schedule", args=[session.id]))

                    notify(
                        request=request,
                        users=head,
                        title="Orientation Scheduling Request",
                        message=(
                            f"Orientation requested: Please schedule {session.department.name} orientation for "
                            f"{staff.get_full_name() or staff.username}."
                        ),
                        category="info",
                        source_app="hr",
                        action_url=url,
                    )

                    if head.email:
                        _send_html_email(
                            subject=f"Orientation Scheduling Request: {staff.get_full_name() or staff.username}",
                            to=[head.email],
                            template="emails/orientation/request_to_head.html",
                            context={
                                "head": head,
                                "staff": staff,
                                "department": session.department,
                                "session": session,
                                "action_url": url,
                                "year": datetime.now().year,
                            },
                        )

                # Notify staff (plan created).

                notify(
                    request=request,
                    users=staff,
                    title="Orientation Scheduling Request",
                    message=(
                        f"HR has initiated your orientation plan. You will receive"
                            " schedules from department heads."
                    ),
                    category="info",
                    source_app="hr",
                    action_url=_orientation_plan_url(request, plan),
                )
                if staff.email:
                    _send_html_email(
                        subject="Your Orientation Plan Has Been Initiated",
                        to=[staff.email],
                        template="emails/orientation/plan_created_to_staff.html",
                        context={
                            "staff": staff,
                            "plan": plan,
                            "year": datetime.now().year,
                        },
                    )

                messages.success(request, "Orientation plan created and department heads notified.")
                return redirect("hr:orientation_hr_detail", plan_id=plan.id)
        messages.error(request, "Please correct the errors below.")
    else:
        form = OrientationPlanCreateForm()

    return render(request, "orientation/hr_create.html", {"staff": staff, "form": form})


@login_required(login_url="login")
def orientation_hr_detail(request, plan_id):
    if not (is_hr(request.user) or request.user.is_superuser or is_department_head(request.user)):
        messages.info(request, "Access denied.")
        return redirect('hr:orientation_my')

    plan = get_object_or_404(
        OrientationPlan.objects.select_related("staff", "staff__department", "created_by").prefetch_related(
            Prefetch("sessions", queryset=OrientationSession.objects.select_related("department", "department__head", "scheduled_by"))
        ),
        id=plan_id,
    )
    return render(request, "orientation/hr_detail.html", {"plan": plan})


@login_required(login_url="login")
def orientation_cmt_list(request):
    if not is_cmt(request.user):
        messages.info(request, "Access denied.")
        return redirect('hr:orientation_my')

    plans = (
        OrientationPlan.objects.select_related("staff", "staff__department")
        .prefetch_related("sessions", "sessions__department")
        .order_by("-created_at")
    )
    return render(request, "orientation/cmt_list.html", {"plans": plans})


@login_required(login_url="login")
def orientation_cmt_detail(request, plan_id):
    if not is_cmt(request.user):
        messages.info(request, "Access denied.")
        return redirect('hr:orientation_my')

    plan = get_object_or_404(
        OrientationPlan.objects.select_related("staff", "staff__department", "created_by").prefetch_related(
            Prefetch("sessions", queryset=OrientationSession.objects.select_related("department", "department__head", "scheduled_by"))
        ),
        id=plan_id,
    )
    sessions = list(plan.sessions.all())
    active_sessions = [
        session for session in sessions
        if session.status != OrientationSessionStatus.CANCELED
    ]
    completed_sessions = [
        session for session in active_sessions
        if session.status == OrientationSessionStatus.COMPLETED
    ]
    scheduled_sessions = [
        session for session in active_sessions
        if session.status == OrientationSessionStatus.SCHEDULED
    ]
    awaiting_sessions = [
        session for session in active_sessions
        if session.status == OrientationSessionStatus.AWAITING_SCHEDULE
    ]

    progress = {
        "total": len(active_sessions),
        "completed": len(completed_sessions),
        "scheduled": len(scheduled_sessions),
        "awaiting": len(awaiting_sessions),
        "canceled": len(sessions) - len(active_sessions),
        "percent": int(round((len(completed_sessions) / len(active_sessions)) * 100))
        if active_sessions else 0,
    }
    return render(
        request,
        "orientation/cmt_detail.html",
        {"plan": plan, "progress": progress},
    )


@login_required(login_url="login")
def orientation_head_list(request):
    if not is_department_head(request.user):
        messages.info(request, "Access denied, only department head can access")
        return redirect('hr:orientation_my')

    sessions = (
        OrientationSession.objects.select_related("plan", "plan__staff", "department", "department__head")
        .filter(department__head=request.user)
        .exclude(status=OrientationSessionStatus.CANCELED)
        .order_by("status", "scheduled_start", "-requested_at")
    )
    return render(request, "orientation/head_list.html", {"sessions": sessions})


@login_required(login_url="login")
def orientation_head_session_schedule(request, session_id):
    session = get_object_or_404(
        OrientationSession.objects.select_related("plan", "plan__staff", "department", "department__head"),
        id=session_id,
    )
    if session.department.head_id != request.user.id:
        messages.info(request, "Access denied, only department head can access")
        return redirect('hr:orientation_my')

    if request.method == "POST":
        form = OrientationSessionScheduleForm(request.POST, instance=session)
        if form.is_valid():
            start = form.cleaned_data["scheduled_start"]
            end = form.cleaned_data["scheduled_end"]
            try:
                session.mark_scheduled(start=start, end=end, by_user=request.user)
            except Exception as e:
                form.add_error(None, str(e))
            else:
                # Notify staff + HR (who created the plan, if any).
                staff = session.plan.staff
                url = request.build_absolute_uri(reverse("hr:orientation_my"))
                notify(
                    request=request,
                    users=staff,
                    title="Orientation Scheduling Request",
                    message=(
                        f"Orientation scheduled with {session.department.name}: "
                        f"{start:%b %d, %Y %H:%M} - {end:%H:%M}."
                    ),
                    category="info",
                    source_app="hr",
                    action_url=url,
                )

                if staff.email:
                    _send_html_email(
                        subject=f"Orientation Scheduled: {session.department.name}",
                        to=[staff.email],
                        template="emails/orientation/scheduled_to_staff.html",
                        context={
                            "staff": staff,
                            "department": session.department,
                            "session": session,
                            "year": datetime.now().year,
                        },
                    )

                hr_user = session.plan.created_by
                if hr_user:
                    notify(
                        request=request,
                        users=hr_user,
                        title="Orientation Scheduling Request",
                        message=(
                            f"{session.department.name} orientation scheduled for "
                            f"{staff.get_full_name() or staff.username}."
                        ),
                        category="info",
                        source_app="hr",
                        action_url=_orientation_plan_url(request, session.plan),
                    )

                    if hr_user.email:
                        _send_html_email(
                        subject=f"Orientation Scheduled ({session.department.name})",
                            to=[hr_user.email],
                            template="emails/orientation/scheduled_to_hr.html",
                            context={
                                "hr": hr_user,
                                "staff": staff,
                                "department": session.department,
                                "session": session,
                                "plan_url": _orientation_plan_url(request, session.plan),
                                "year": datetime.now().year,
                            },
                        )

                messages.success(request, "Orientation session scheduled and notifications sent.")
                return redirect("hr:orientation_head_list")
        messages.error(request, "Please correct the errors below.")
    else:
        form = OrientationSessionScheduleForm(instance=session)

    return render(request, "orientation/head_schedule.html", {"session": session, "form": form})


@login_required(login_url="login")
def orientation_head_session_complete(request, session_id):
    session = get_object_or_404(
        OrientationSession.objects.select_related("plan", "plan__staff", "department", "department__head"),
        id=session_id,
    )
    if session.department.head_id != request.user.id:
        return HttpResponseForbidden("Access denied.")

    if session.status not in {OrientationSessionStatus.SCHEDULED, OrientationSessionStatus.COMPLETED}:
        messages.error(request, "This session must be scheduled before it can be completed.")
        return redirect("hr:orientation_head_list")

    if request.method == "POST":
        form = OrientationSessionCompleteForm(request.POST, instance=session)
        if form.is_valid():
            notes = form.cleaned_data.get("completion_notes", "")
            session.mark_completed(by_user=request.user, notes=notes)
            session.plan.refresh_status_from_sessions()

            staff = session.plan.staff
            hr_user = session.plan.created_by

            if hr_user:
                notify(
                    request=request,
                    users=hr_user,
                    title="Orientation Scheduling Request",
                    message=(
                        f"Orientation completed: {session.department.name} confirmed completion for "
                        f"{staff.get_full_name() or staff.username}. Please review progress."
                    ),
                    category="info",
                    source_app="hr",
                    action_url=_orientation_plan_url(request, session.plan),
                )
                if hr_user.email:
                    _send_html_email(
                        subject=f"Orientation Completed ({session.department.name})",
                        to=[hr_user.email],
                        template="emails/orientation/completed_to_hr.html",
                        context={
                            "hr": hr_user,
                            "staff": staff,
                            "department": session.department,
                            "session": session,
                            "plan_url": _orientation_plan_url(request, session.plan),
                            "year": datetime.now().year,
                        },
                    )

            notify(
                request=request,
                users=staff,
                title="Orientation Scheduling Request",
                message=(
                    f"{session.department.name} orientation marked complete."
                ),
                category="info",
                source_app="hr",
                        action_url=request.build_absolute_uri(reverse("hr:orientation_my")),
            )

            messages.success(request, "Session marked as completed and HR notified.")
            return redirect("hr:orientation_head_list")
        messages.error(request, "Please correct the errors below.")
    else:
        form = OrientationSessionCompleteForm(instance=session)

    return render(request, "orientation/head_complete.html", {"session": session, "form": form})


@login_required(login_url="login")
def orientation_my(request):
    staff = request.user
    plan = OrientationPlan.objects.filter(staff=staff).prefetch_related("sessions", "sessions__department").first()
    return render(request, "orientation/my_plan.html", {"plan": plan})
