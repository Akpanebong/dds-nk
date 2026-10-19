import os
from collections import defaultdict
from datetime import date, datetime
from email.mime.image import MIMEImage
from io import BytesIO
from typing import Optional, Tuple
from django.conf import settings
from django.core.files.base import ContentFile
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.core.mail import EmailMultiAlternatives
from xhtml2pdf import pisa
from core.models import StaffProfile as Profile
from notifications.models import Notification
from .models import Leave, LeaveDocument, LeaveType, Employee


def notify(*, request=None, users=None, title='', message='', action_url='', **kwargs):
    recipients = users if hasattr(users, '__iter__') and not hasattr(users, 'pk') else [users]
    for recipient in recipients:
        if recipient and getattr(recipient, 'pk', None):
            Notification.objects.create(recipient=recipient, title=title, message=message,
                                        url=action_url or '')


def _send_html_email(*, subject, to, template=None, context=None, html_message=None, **kwargs):
    if not to:
        return
    body = html_message or (render_to_string(template, context or {}) if template else '')
    EmailMultiAlternatives(subject, '', settings.DEFAULT_FROM_EMAIL,
                           to if isinstance(to, list) else [to],
                           alternatives=[(body, 'text/html')]).send(fail_silently=True)


# PDF templates may optionally use a logo. Keep this unset until a current
# organisation asset is configured.
logo_path = None


def render_to_pdf(template_src, context_dict={}):
    html = render_to_string(template_src, context_dict)
    result = BytesIO()

    pdf = pisa.pisaDocument(BytesIO(html.encode("UTF-8")), result)

    if not pdf.err:
        return HttpResponse(
            result.getvalue(),
            content_type="application/pdf"
        )

    return HttpResponse("Error generating PDF", status=500)


def _html_to_pdf_bytes(html_string):
    """
    Uses xhtml2pdf (pisa) to convert HTML string to PDF bytes.
    Returns bytes or None on failure.
    """
    result = BytesIO()
    # note: pisaDocument accepts bytes stream; we ensure UTF-8 encoding
    pdf = pisa.pisaDocument(BytesIO(html_string.encode('utf-8')), dest=result,
                            encoding='utf-8')
    if pdf.err:
        return None
    return result.getvalue()


def render_template_to_pdf_bytes(template_name, context):
    html = render_to_string(template_name, context)
    return _html_to_pdf_bytes(html)


def generate_and_save_staff_hr_pdfs(leave):
    employee = leave.employee
    current_year = date.today().year

    year_start = date(int(current_year), 1, 1)
    year_end = date(int(current_year), 12, 31)
    leaves = (
        Leave.objects.filter(
            employee=employee,
            status="Approved",
            start_date__lte=year_end,
            end_date__gte=year_start,
        )
        .order_by("start_date")
    )

    leave_types = LeaveType.objects.all()
    balances = {lt.id: int(lt.no_of_days or 0) for lt in leave_types}

    rows = []

    for l in leaves:
        days = int(getattr(l, "working_days", 0) or l.days_requested)

        lt_id = l.leave_type_id

        if lt_id in balances:
            balances[lt_id] -= days
            balances[lt_id] = max(0, balances[lt_id])

        rows.append({
            "leave": l,
            "days_requested": days,
            "entitled_days": int(getattr(l.leave_type, "no_of_days", 0) or 0),
            "remaining_days": balances.get(lt_id, 0),
        })
    saved_docs = []
    for copy_title in ("STAFF COPY", "HUMAN RESOURCE COPY"):
        context = {
            "employee": employee,
            "rows": rows,
            "copy_title": copy_title,
            "generated_at": datetime.now(),
            "logo_path": logo_path,
        }

        pdf_bytes = render_template_to_pdf_bytes(
            "hr/leave_card_pdf.html", context
        )
        if not pdf_bytes:
            continue

        filename = f"leave_{employee.username}_{copy_title.replace(' ','_')}_{leave.id}.pdf"
        doc = LeaveDocument.objects.create(leave=leave)
        doc.file.save(filename, ContentFile(pdf_bytes))
        saved_docs.append(doc)

    return saved_docs



def _overlap_working_days(*, leave: Leave, start: date, end: date) -> int:
    """
    Working days within the overlap of [leave.start_date, leave.end_date] and [start, end].
    """
    if not start or not end or end < start:
        return 0

    if leave.end_date < start or leave.start_date > end:
        return 0

    effective_start = max(leave.start_date, start)
    effective_end = min(leave.end_date, end)
    return int(Leave.compute_working_days(effective_start, effective_end) or 0)


def _year_bounds(year: int) -> Tuple[date, date]:
    return date(int(year), 1, 1), date(int(year), 12, 31)


def _clamp_to_year(*, year: int, start_date: Optional[date], end_date: Optional[date]) -> Tuple[date, date]:
    year_start, year_end = _year_bounds(year)
    start = max(year_start, start_date) if start_date else year_start
    end = min(year_end, end_date) if end_date else year_end
    if end < start:
        return year_start, year_end
    return start, end


def yearly_leave_allocation_report(*, year: int, start_date: Optional[date] = None, end_date: Optional[date] = None):
    """
    Organization-wide report for the year:
    - approved days (sum of working days) per leave type
    - allotted days per leave type (staff_count * LeaveType.no_of_days)
    """
    report_start, report_end = _clamp_to_year(year=year, start_date=start_date, end_date=end_date)

    staff_qs = Employee.objects.filter(
        is_active=True,
        user_type__in=[
            Profile.UserType.STAFF,
            Profile.UserType.INTERN,
            Profile.UserType.VOLUNTEER,
        ],
    )
    staff_count = staff_qs.count()

    approved_leaves = (
        Leave.objects.filter(
            status="Approved",
            start_date__lte=report_end,
            end_date__gte=report_start,
        )
        .select_related("leave_type")
        .only("id", "leave_type_id", "start_date", "end_date")
    )

    approved_totals: dict[int, int] = defaultdict(int)
    for leave in approved_leaves:
        approved_totals[leave.leave_type_id] += _overlap_working_days(leave=leave, start=report_start, end=report_end)

    report_rows = []
    for lt in LeaveType.objects.all().order_by("name"):
        allotted_per_staff = int(lt.no_of_days or 0)
        allotted_total = staff_count * allotted_per_staff
        approved_total = approved_totals.get(lt.id, 0)
        report_rows.append(
            {
                "year": int(year),
                "start_date": report_start,
                "end_date": report_end,
                "leave_type": lt,
                "staff_count": staff_count,
                "allotted_per_staff": allotted_per_staff,
                "allotted_total_days": allotted_total,
                "approved_total_days": approved_total,
                "usage_percentage": round((approved_total / allotted_total) * 100, 1) if allotted_total else 0,
                "remaining_total_days": max(0, allotted_total - approved_total),
            }
        )

    return report_rows


def staff_leave_balance_report(
    *,
    year: int,
    leave_type: LeaveType,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    include_zero: bool = True,
):
    """
    Staff-level balances for the given year + leave_type.

    Returns rows:
      {"employee": Profile, "allotted_days": int, "taken_days": int, "remaining_days": int}
    """
    report_start, report_end = _clamp_to_year(year=year, start_date=start_date, end_date=end_date)

    staff_qs = (
        Employee.objects.filter(
            is_active=True,
            user_type__in=[
                Profile.UserType.STAFF,
                Profile.UserType.INTERN,
                Profile.UserType.VOLUNTEER,
            ],
        )
        .order_by("last_name", "first_name", "username")
    )
    allotted_per_staff = int(getattr(leave_type, "no_of_days", 0) or 0)

    leaves = (
        Leave.objects.filter(
            status="Approved",
            leave_type=leave_type,
            start_date__lte=report_end,
            end_date__gte=report_start,
        )
        .select_related("employee")
        .only("id", "employee_id", "start_date", "end_date")
    )

    taken_by_employee: dict[int, int] = defaultdict(int)
    for leave in leaves:
        taken_by_employee[leave.employee_id] += _overlap_working_days(leave=leave, start=report_start, end=report_end)

    rows = []
    if include_zero:
        for staff in staff_qs:
            taken = int(taken_by_employee.get(staff.id, 0) or 0)
            rows.append(
                {
                    "year": int(year),
                    "start_date": report_start,
                    "end_date": report_end,
                    "leave_type": leave_type,
                    "employee": staff,
                    "allotted_days": allotted_per_staff,
                    "taken_days": taken,
                    "remaining_days": max(0, allotted_per_staff - taken),
                }
            )
        return rows

    profiles = Profile.objects.in_bulk(list(taken_by_employee.keys()))
    for emp_id, taken in taken_by_employee.items():
        profile = profiles.get(emp_id)
        if profile is None:
            continue
        rows.append(
            {
                "year": int(year),
                "start_date": report_start,
                "end_date": report_end,
                "leave_type": leave_type,
                "employee": profile,
                "allotted_days": allotted_per_staff,
                "taken_days": int(taken or 0),
                "remaining_days": max(0, allotted_per_staff - int(taken or 0)),
            }
        )
    return rows


def employee_leave_balances(
    *,
    employee: Profile,
    year: int,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
):
    """
    Per-leave-type balances for a single employee.

    Returns rows:
      {"leave_type": LeaveType, "allotted_days": int, "taken_days": int, "remaining_days": int}
    """
    report_start, report_end = _clamp_to_year(year=year, start_date=start_date, end_date=end_date)
    leaves = (
        Leave.objects.filter(
            status="Approved",
            employee=employee,
            start_date__lte=report_end,
            end_date__gte=report_start,
        )
        .select_related("leave_type")
        .only("id", "leave_type_id", "start_date", "end_date")
    )

    taken_by_type: dict[int, int] = defaultdict(int)
    for leave in leaves:
        taken_by_type[leave.leave_type_id] += _overlap_working_days(leave=leave, start=report_start, end=report_end)

    rows = []
    for lt in LeaveType.objects.all().order_by("name"):
        allotted = int(lt.no_of_days or 0)
        taken = int(taken_by_type.get(lt.id, 0) or 0)
        rows.append(
            {
                "year": int(year),
                "start_date": report_start,
                "end_date": report_end,
                "leave_type": lt,
                "allotted_days": allotted,
                "taken_days": taken,
                "remaining_days": allotted - taken,
            }
        )
    return rows

