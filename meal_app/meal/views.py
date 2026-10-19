from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone

from core.access import access_required, crud_access_required
from core.utils import audit, recent_audit_activity, stamp_audit as _stamp_audit
from notifications.services import notify_group, notify_user
from .forms import (ActivityForm, ActivityRecordBaseForm, IndicatorForm, NonPeopleActivityRecordForm,
                    OutputForm, PeopleActivityRecordForm, QuarterPlanForm, StrategicObjectiveForm)
from .models import ACTIVITY_STATUSES, ActivityRecord, Indicator, Output, QuarterPlan, StrategicObjective
from django.db.models.functions import Coalesce, TruncMonth
from django.shortcuts import render
from decimal import Decimal
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Sum, Avg, Q, F, Value, DecimalField, ExpressionWrapper


def _quarterplan_form_context():
    return {
        'quarterplan_form': True,
        'indicator_metadata': {
            str(item.pk): {
                'target': '' if item.target is None else str(item.target),
                'quarter': item.quarter or '',
            }
            for item in Indicator.objects.only('pk', 'target', 'quarter')
        },
    }


QUARTERS = ("Q1", "Q2", "Q3", "Q4")
QUARTER_MONTHS = {
    "Q1": (1, 2, 3),
    "Q2": (4, 5, 6),
    "Q3": (7, 8, 9),
    "Q4": (10, 11, 12),
}


def _selected_quarter(request):
    quarter = (request.GET.get("quarter") or "Q1").upper()
    return quarter if quarter in QUARTERS else "Q1"


def _tracker_years():
    years = set(QuarterPlan.objects.values_list("reporting_year", flat=True))
    years.update(ActivityRecord.objects.values_list("reporting_year", flat=True))
    years.add(2026)
    return sorted(years, reverse=True)


def _selected_tracker_year(request):
    try:
        year = int(request.GET.get("year", 2026))
    except (TypeError, ValueError):
        year = 2026
    return year if 2020 <= year <= 2100 else 2026


def _quarter_rows(quarter, year=2026):
    plans = list(
        QuarterPlan.objects.filter(
            quarter=quarter,
            reporting_year=year,
            indicator__active=True,
        ).select_related("indicator", "indicator__output", "indicator__output__objective")
    )
    months = QUARTER_MONTHS[quarter]
    records = ActivityRecord.objects.filter(
        reporting_year=year,
        reporting_month__in=months,
    ).select_related("indicator")
    record_values = {}
    for record in records:
        value = record.total_people if record.indicator.is_people else record.progress_value
        record_values[record.indicator_id] = record_values.get(record.indicator_id, Decimal("0")) + (value or Decimal("0"))

    rows = []
    for plan in plans:
        target = plan.target or Decimal("0")
        result = record_values[plan.indicator_id] if plan.indicator_id in record_values else (plan.workbook_result or Decimal("0"))
        achievement = min(max(float(result / target * 100), 0), 100) if target else 0
        rows.append({
            "indicator": plan.indicator,
            "code": plan.indicator.code,
            "title": plan.indicator.title,
            "output": plan.indicator.output,
            "target": float(target),
            "result": float(result),
            "achievement": round(achievement, 1),
            "planned_budget": float(plan.planned_budget or 0),
            "budget_expense": float(plan.budget_expense or 0),
            "variance": float((plan.planned_budget or 0) - (plan.budget_expense or 0)),
            "has_live_record": plan.indicator_id in record_values,
        })
    return rows


def _group_output_rows(rows):
    grouped = {}
    for row in rows:
        output = row["output"]
        bucket = grouped.setdefault(output.id, {
            "code": output.code,
            "title": output.title,
            "objective": output.objective.title if output.objective else "",
            "indicators": [],
            "target": 0,
            "result": 0,
            "planned_budget": 0,
            "budget_expense": 0,
        })
        bucket["indicators"].append(row)
        for key in ("target", "result", "planned_budget", "budget_expense"):
            bucket[key] += row[key]
    for bucket in grouped.values():
        bucket["achievement"] = round(min(max(bucket["result"] / bucket["target"] * 100, 0), 100), 1) if bucket["target"] else 0
        bucket["variance"] = bucket["planned_budget"] - bucket["budget_expense"]
    return list(grouped.values())


def _fy26_rows(year=2026):
    plans = list(
        QuarterPlan.objects.filter(reporting_year=year, indicator__active=True)
        .select_related("indicator", "indicator__output", "indicator__output__objective")
    )
    records = ActivityRecord.objects.filter(reporting_year=year).select_related("indicator")
    record_values = {}
    for record in records:
        value = record.total_people if record.indicator.is_people else record.progress_value
        record_values[record.indicator_id] = record_values.get(record.indicator_id, Decimal("0")) + (value or Decimal("0"))
    by_indicator = {}
    for plan in plans:
        bucket = by_indicator.setdefault(plan.indicator_id, {
            "indicator": plan.indicator,
            "output": plan.indicator.output,
            "target": float(plan.indicator.target or 0),
            "result": 0,
            "planned_budget": 0,
            "budget_expense": 0,
        })
        bucket["result"] += float(plan.workbook_result or 0)
        bucket["planned_budget"] += float(plan.planned_budget or 0)
        bucket["budget_expense"] += float(plan.budget_expense or 0)
    for indicator_id, bucket in by_indicator.items():
        if indicator_id in record_values:
            bucket["result"] = float(record_values[indicator_id])
        bucket["achievement"] = round(min(max(bucket["result"] / bucket["target"] * 100, 0), 100), 1) if bucket["target"] else 0
    return list(by_indicator.values())



@access_required('meal')
def dashboard(request):

    # ========================================================================
    # FILTERS
    # ========================================================================

    current_year = timezone.now().year

    year_param = request.GET.get("year")
    if year_param in {"", "all"}:
        selected_year = None
    else:
        try:
            selected_year = int(
                year_param or current_year
            )
        except (TypeError, ValueError):
            selected_year = current_year

    objective_id = request.GET.get("objective") or ""
    output_id = request.GET.get("output") or ""
    activity_type = request.GET.get("activity_type") or ""
    status = request.GET.get("status") or ""

    # ========================================================================
    # BASE INDICATOR QUERYSET
    # ========================================================================

    indicators = (
        Indicator.objects
        .filter(active=True)
        .select_related(
            "output",
            "output__objective",
        )
    )

    if objective_id:
        indicators = indicators.filter(
            output__objective_id=objective_id
        )

    if output_id:
        indicators = indicators.filter(
            output_id=output_id
        )

    if activity_type in {"people", "non_people"}:
        indicators = indicators.filter(
            activity_type=activity_type
        )

    indicator_ids = indicators.values_list(
        "id",
        flat=True,
    )

    # ========================================================================
    # BASE RECORD QUERYSET
    # ========================================================================

    records = (
        ActivityRecord.objects
        .filter(indicator_id__in=indicator_ids)
        .select_related(
            "indicator",
            "indicator__output",
            "indicator__output__objective",
            "submitted_by",
        )
    )

    if selected_year is not None:
        records = records.filter(reporting_year=selected_year)

    if status in {
        "pending",
        "in_progress",
        "completed",
        "on_hold",
    }:
        records = records.filter(
            status=status
        )

    # ========================================================================
    # BASIC COUNTS
    # ========================================================================

    objective_count = StrategicObjective.objects.count()

    output_count = Output.objects.count()

    activity_count = indicators.count()

    people_count = indicators.filter(
        activity_type="people"
    ).count()

    non_people_count = indicators.filter(
        activity_type="non_people"
    ).count()

    record_count = records.count()

    pending_count = records.filter(
        status="pending"
    ).count()

    in_progress_count = records.filter(
        status="in_progress"
    ).count()

    completed_count = records.filter(
        status="completed"
    ).count()

    on_hold_count = records.filter(
        status="on_hold"
    ).count()

    # ========================================================================
    # PEOPLE METRICS
    # ========================================================================

    people_totals = records.filter(
        indicator__activity_type="people"
    ).aggregate(
        women=Sum("women"),
        men=Sum("men"),
        male_youth=Sum("male_youth"),
        female_youth=Sum("female_youth"),
        boys=Sum("boys"),
        girls=Sum("girls"),
        pwd_male=Sum("pwd_male"),
        pwd_female=Sum("pwd_female"),
    )

    women_total = people_totals["women"] or 0
    men_total = people_totals["men"] or 0

    male_youth_total = people_totals["male_youth"] or 0
    female_youth_total = people_totals["female_youth"] or 0

    boys_total = people_totals["boys"] or 0
    girls_total = people_totals["girls"] or 0

    pwd_male_total = people_totals["pwd_male"] or 0
    pwd_female_total = people_totals["pwd_female"] or 0

    total_youth = (
        male_youth_total
        + female_youth_total
    )

    total_children = (
        boys_total
        + girls_total
    )

    total_pwd = (
        pwd_male_total
        + pwd_female_total
    )

    total_people = (
        women_total
        + men_total
        + total_youth
        + total_children
    )

    # ========================================================================
    # PROGRESS
    # ========================================================================
    #
    # Progress is accumulated from the selected reporting-year records.
    #
    # Targets are calculated from DISTINCT indicators, so a monthly activity
    # with 12 records does not have its annual target multiplied by 12.
    # ========================================================================

    non_people_progress = (
        records
        .filter(indicator__activity_type="non_people")
        .aggregate(total=Sum("progress_value"))["total"]
        or Decimal("0")
    )

    people_progress_row = (
        records
        .filter(indicator__activity_type="people")
        .aggregate(
            women=Sum("women"),
            men=Sum("men"),
            male_youth=Sum("male_youth"),
            female_youth=Sum("female_youth"),
            boys=Sum("boys"),
            girls=Sum("girls"),
        )
    )
    people_progress = sum(
        people_progress_row.get(field) or 0
        for field in (
            "women",
            "men",
            "male_youth",
            "female_youth",
            "boys",
            "girls",
        )
    )
    total_progress = Decimal(non_people_progress) + Decimal(people_progress)

    total_targets = (
        indicators.filter(activity_type="people").aggregate(
            total=Sum("target")
        )["total"]
        or Decimal("0")
    )

    if total_targets:
        overall_progress_percent = round(
            float(
                total_progress
                / total_targets
                * 100
            ),
            1,
        )
    else:
        overall_progress_percent = 0

    progress_display_percent = min(
        max(overall_progress_percent, 0),
        100,
    )

    # ========================================================================
    # COMPLETION RATE
    # ========================================================================

    completion_rate = (
        round(
            completed_count / record_count * 100,
            1,
        )
        if record_count
        else 0
    )

    # ========================================================================
    # OBJECTIVE PERFORMANCE
    # ========================================================================

    objective_rows = (
        indicators
        .values(
            "output__objective_id",
            "output__objective__code",
            "output__objective__title",
        )
        .annotate(
            activity_count=Count(
                "id",
                distinct=True,
            ),
            target_total=Sum("target", filter=Q(activity_type="people")),
        )
        .order_by(
            "output__objective__code"
        )
    )

    objective_progress = (
        records
        .values(
            "indicator__output__objective_id"
        )
        .annotate(
            progress_total=Sum("progress_value"),
            women_total=Sum("women"),
            men_total=Sum("men"),
            male_youth_total=Sum("male_youth"),
            female_youth_total=Sum("female_youth"),
            boys_total=Sum("boys"),
            girls_total=Sum("girls"),
            record_total=Count(
                "id"
            ),
            completed_total=Count(
                "id",
                filter=Q(status="completed")
            ),
        )
    )

    objective_progress_map = {
        row[
            "indicator__output__objective_id"
        ]: row
        for row in objective_progress
    }

    objective_performance = []

    for row in objective_rows:

        objective_id_value = row[
            "output__objective_id"
        ]

        progress_row = objective_progress_map.get(
            objective_id_value,
            {},
        )

        non_people_progress = (
            progress_row.get("progress_total")
            or Decimal("0")
        )
        people_progress = sum(
            progress_row.get(field) or 0
            for field in (
                "women_total",
                "men_total",
                "male_youth_total",
                "female_youth_total",
                "boys_total",
                "girls_total",
            )
        )
        progress = Decimal(non_people_progress) + Decimal(people_progress)

        target = (
            row["target_total"]
            or Decimal("0")
        )

        achievement = (
            round(
                float(progress / target * 100),
                1,
            )
            if target
            else 0
        )

        objective_performance.append({
            "code": row[
                "output__objective__code"
            ],
            "title": row[
                "output__objective__title"
            ],
            "activities": row[
                "activity_count"
            ],
            "records": progress_row.get(
                "record_total",
                0,
            ),
            "completed": progress_row.get(
                "completed_total",
                0,
            ),
            "progress": float(progress),
            "target": float(target),
            "achievement": min(
                max(achievement, 0),
                100,
            ),
        })

    # ========================================================================
    # MONTHLY REPORTING
    # ========================================================================

    monthly_rows = (
        records
        .filter(
            reporting_month__isnull=False
        )
        .values(
            "reporting_month"
        )
        .annotate(
            completed=Count(
                "id",
                filter=Q(
                    status="completed"
                ),
            ),
            pending=Count(
                "id",
                filter=Q(
                    status="pending"
                ),
            ),
            in_progress=Count(
                "id",
                filter=Q(status="in_progress"),
            ),
            on_hold=Count(
                "id",
                filter=Q(status="on_hold"),
            ),
            progress=Sum(
                "progress_value"
            ),
        )
        .order_by(
            "reporting_month"
        )
    )

    month_names = [
        "",
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    ]

    monthly_labels = []
    monthly_completed = []
    monthly_pending = []
    monthly_in_progress = []
    monthly_on_hold = []
    monthly_progress = []

    monthly_map = {
        row["reporting_month"]: row
        for row in monthly_rows
    }

    for month in range(1, 13):

        row = monthly_map.get(
            month,
            {},
        )

        monthly_labels.append(
            month_names[month]
        )

        monthly_completed.append(
            row.get("completed", 0)
        )

        monthly_pending.append(
            row.get("pending", 0)
        )

        monthly_in_progress.append(row.get("in_progress", 0))
        monthly_on_hold.append(row.get("on_hold", 0))

        monthly_progress.append(
            float(
                row.get("progress")
                or Decimal("0")
            )
        )

    # ========================================================================
    # ACTIVITY TYPE DISTRIBUTION
    # ========================================================================

    activity_type_rows = (
        indicators
        .values("activity_type")
        .annotate(
            total=Count("id")
        )
    )

    activity_type_map = {
        row["activity_type"]: row["total"]
        for row in activity_type_rows
    }

    activity_type_labels = [
        "People",
        "Non-people",
    ]

    activity_type_values = [
        activity_type_map.get(
            "people",
            0,
        ),
        activity_type_map.get(
            "non_people",
            0,
        ),
    ]

    # ========================================================================
    # STATUS DISTRIBUTION
    # ========================================================================

    status_rows = (
        records
        .values("status")
        .annotate(
            total=Count("id")
        )
    )

    status_map = {
        row["status"]: row["total"]
        for row in status_rows
    }

    status_labels = [label for value, label in ACTIVITY_STATUSES]
    status_values = [status_map.get(value, 0) for value, label in ACTIVITY_STATUSES]

    # ========================================================================
    # TOP ACTIVITIES
    # ========================================================================
    #
    # Calculate progress in one grouped query instead of looping over
    # activities and hitting the database repeatedly.
    # ========================================================================

    activity_progress_rows = (
        records
        .values(
            "indicator_id",
            "indicator__code",
            "indicator__title",
            "indicator__activity_type",
            "indicator__target",
        )
        .annotate(
            progress=Sum("progress_value"),
            women=Sum("women"),
            men=Sum("men"),
            male_youth=Sum("male_youth"),
            female_youth=Sum("female_youth"),
            boys=Sum("boys"),
            girls=Sum("girls"),
            record_count=Count("id"),
        )
    )

    top_activities = []

    for row in activity_progress_rows:

        if row["indicator__activity_type"] == "people":
            # People records use the disaggregated fields as their achieved
            # value. progress_value is intentionally not shown on that form.
            progress = sum(
                row.get(field) or 0
                for field in (
                    "women",
                    "men",
                    "male_youth",
                    "female_youth",
                    "boys",
                    "girls",
                )
            )
        else:
            progress = row["progress"] or Decimal("0")
        progress = Decimal(progress)

        is_non_people = row["indicator__activity_type"] == "non_people"
        target = Decimal("0") if is_non_people else (row["indicator__target"] or Decimal("0"))

        achievement = (
            round(float(progress / target * 100), 1)
            if target else 0
        )

        achievement = min(
            max(achievement, 0),
            100,
        )

        # A target is required for a meaningful achievement percentage. If
        # progress has nevertheless been recorded, show it visually without
        # misrepresenting the result as a percentage achievement.
        if target:
            bar_width = achievement
        elif is_non_people:
            # Non-people records are recorded values, not target-based
            # percentage achievements on this dashboard.
            bar_width = 100 if progress > 0 else 0
        else:
            bar_width = 100 if progress > 0 else 0

        if is_non_people:
            performance_status = "Recorded"
        elif not target:
            performance_status = "No target"
        elif achievement >= 75:
            performance_status = "On track"
        elif achievement >= 40:
            performance_status = "Needs attention"
        else:
            performance_status = "At risk"

        top_activities.append({
            "code": row[
                "indicator__code"
            ],
            "title": row[
                "indicator__title"
            ],
            "type": (
                "People"
                if row[
                    "indicator__activity_type"
                ] == "people"
                else "Non-people"
            ),
            "progress": float(progress),
            "target": float(target),
            "is_non_people": is_non_people,
            "achievement": achievement,
            "bar_width": bar_width,
            "record_count": row[
                "record_count"
            ],
            "status": performance_status,
        })

    top_activities.sort(
        key=lambda item: item["achievement"],
        reverse=True,
    )

    top_activities = top_activities[:8]

    # ========================================================================
    # RECENT RECORDS
    # ========================================================================

    recent_records = records.order_by(
        "-created_at"
    )[:10]

    # ========================================================================
    # FILTER OPTIONS
    # ========================================================================

    objectives = StrategicObjective.objects.order_by(
        "code"
    )

    outputs = Output.objects.select_related(
        "objective"
    ).order_by(
        "code"
    )

    years = (
        ActivityRecord.objects
        .values_list(
            "reporting_year",
            flat=True,
        )
        .distinct()
        .order_by(
            "-reporting_year"
        )
    )

    years = list(years)

    if selected_year is not None and selected_year not in years:
        years.insert(
            0,
            selected_year,
        )

    # ========================================================================
    # CHART JSON
    # ========================================================================

    chart_data = {
        "monthly_labels": monthly_labels,
        "monthly_completed": monthly_completed,
        "monthly_pending": monthly_pending,
        "monthly_in_progress": monthly_in_progress,
        "monthly_on_hold": monthly_on_hold,
        "monthly_progress": monthly_progress,

        "activity_type_labels": activity_type_labels,
        "activity_type_values": activity_type_values,

        "status_labels": status_labels,
        "status_values": status_values,

        "people_labels": [
            "Women",
            "Men",
            "Youth",
            "Children",
            "PWD",
        ],

        "people_values": [
            women_total,
            men_total,
            total_youth,
            total_children,
            total_pwd,
        ],
    }

    # ========================================================================
    # CONTEXT
    # ========================================================================

    context = {

        # Filters
        "selected_year": selected_year,
        "selected_year_display": selected_year or "All years",
        "period_label": f"FY{str(selected_year)[-2:]}" if selected_year else "All years",
        "selected_objective": objective_id,
        "selected_output": output_id,
        "selected_activity_type": activity_type,
        "selected_status": status,

        "years": years,
        "objectives": objectives,
        "outputs": outputs,

        # Primary KPIs
        "objective_count": objective_count,
        "output_count": output_count,
        "activity_count": activity_count,
        "people_count": people_count,
        "non_people_count": non_people_count,

        # Records
        "record_count": record_count,
        "pending_count": pending_count,
        "in_progress_count": in_progress_count,
        "completed_count": completed_count,
        "on_hold_count": on_hold_count,

        # People
        "total_people": total_people,
        "total_youth": total_youth,
        "total_children": total_children,
        "total_pwd": total_pwd,

        "women_total": women_total,
        "men_total": men_total,
        "male_youth_total": male_youth_total,
        "female_youth_total": female_youth_total,
        "boys_total": boys_total,
        "girls_total": girls_total,
        "pwd_male_total": pwd_male_total,
        "pwd_female_total": pwd_female_total,
        "people_kpis": [
            ("Women", women_total, "bi-person-standing-dress"),
            ("Men", men_total, "bi-person-standing"),
            ("Male youth", male_youth_total, "bi-person"),
            ("Female youth", female_youth_total, "bi-person"),
            ("Boys", boys_total, "bi-person-fill"),
            ("Girls", girls_total, "bi-person-fill"),
            ("PWD male", pwd_male_total, "bi-universal-access"),
            ("PWD female", pwd_female_total, "bi-universal-access"),
        ],

        # Performance
        "total_progress": total_progress,
        "total_targets": total_targets,
        "overall_progress_percent": overall_progress_percent,
        "progress_display_percent": progress_display_percent,
        "completion_rate": completion_rate,

        # Analysis
        "objective_performance": objective_performance,
        "top_activities": top_activities,
        "recent_records": recent_records,

        # Charts
        "chart_data": chart_data,
        "recent_activity": recent_audit_activity(request.user),
    }

    return render(
        request,
        "meal/dashboard.html",
        context,
    )


@access_required('meal')
def iptt(request):
    quarter = _selected_quarter(request)
    year = _selected_tracker_year(request)
    rows = _quarter_rows(quarter, year)
    output_rows = _group_output_rows(rows)
    return render(request, 'meal/iptt.html', {
        'quarter': quarter,
        'quarters': QUARTERS,
        'rows': rows,
        'output_rows': output_rows,
        'year': year,
        'years': _tracker_years(),
    })


@access_required('meal')
def output_dashboard(request):
    quarter = _selected_quarter(request)
    year = _selected_tracker_year(request)
    rows = _quarter_rows(quarter, year)
    output_rows = _group_output_rows(rows)
    return render(request, 'meal/output_dashboard.html', {
        'quarter': quarter,
        'year': year,
        'years': _tracker_years(),
        'quarters': QUARTERS,
        'output_rows': output_rows,
        'chart_data': {
            'labels': [item['code'] for item in output_rows],
            'targets': [item['target'] for item in output_rows],
            'results': [item['result'] for item in output_rows],
        },
    })


@access_required('meal')
def finance_dashboard(request):
    quarter = _selected_quarter(request)
    year = _selected_tracker_year(request)
    rows = _quarter_rows(quarter, year)
    output_rows = _group_output_rows(rows)
    total_planned = sum(item['planned_budget'] for item in output_rows)
    total_expense = sum(item['budget_expense'] for item in output_rows)
    return render(request, 'meal/finance.html', {
        'quarter': quarter,
        'year': year,
        'years': _tracker_years(),
        'quarters': QUARTERS,
        'output_rows': output_rows,
        'total_planned': total_planned,
        'total_expense': total_expense,
        'total_variance': total_planned - total_expense,
        'chart_data': {
            'labels': [item['code'] for item in output_rows],
            'planned': [item['planned_budget'] for item in output_rows],
            'expense': [item['budget_expense'] for item in output_rows],
        },
    })


@access_required('meal')
def fy26_output_dashboard(request):
    quarter = _selected_quarter(request)
    year = _selected_tracker_year(request)
    rows = _fy26_rows(year)
    grouped = {}
    for row in rows:
        output = row['output']
        bucket = grouped.setdefault(output.id, {
            'code': output.code,
            'title': output.title,
            'objective': output.objective.title if output.objective else '',
            'target': 0,
            'result': 0,
            'planned_budget': 0,
            'budget_expense': 0,
            'indicators': [],
        })
        bucket['target'] += row['target']
        bucket['result'] += row['result']
        bucket['planned_budget'] += row['planned_budget']
        bucket['budget_expense'] += row['budget_expense']
        bucket['indicators'].append(row)
    output_rows = list(grouped.values())
    for item in output_rows:
        item['achievement'] = round(min(max(item['result'] / item['target'] * 100, 0), 100), 1) if item['target'] else 0
        item['variance'] = item['planned_budget'] - item['budget_expense']
    return render(request, 'meal/fy26_output_dashboard.html', {
        'quarter': quarter,
        'year': year,
        'years': _tracker_years(),
        'output_rows': output_rows,
        'chart_data': {
            'labels': [item['code'] for item in output_rows],
            'targets': [item['target'] for item in output_rows],
            'results': [item['result'] for item in output_rows],
        },
    })


@access_required('meal')
def tracker_export(request):
    from .exports import tracker_workbook_response

    year = _selected_tracker_year(request)
    quarter = _selected_quarter(request)
    return tracker_workbook_response(year, quarter)


@access_required('meal')
def activity_list(request):
    qs = Indicator.objects.filter(active=True).select_related('output__objective')
    kind = request.GET.get('type')
    q = request.GET.get('q', '').strip()
    if kind in {'people', 'non_people'}:
        qs = qs.filter(activity_type=kind)
    if q:
        qs = qs.filter(title__icontains=q) | qs.filter(code__icontains=q) | qs.filter(indicator_text__icontains=q)
    qs = qs.order_by('code')
    paginator = Paginator(qs, 10)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'meal/activities.html', {
        'activities': page_obj,
        'page_obj': page_obj,
        'activity_count': paginator.count,
        'q': q,
        'kind': kind,
        'current_year': timezone.localdate().year,
    })


@crud_access_required('meal')
def activity_create(request):
    form = ActivityForm(request.POST or None)

    if form.is_valid():
        activity = _stamp_audit(
            form.save(commit=False),
            request.user,
            creating=True
        )

        activity.save()

        audit(
            request,
            'Created MEAL activity',
            'MEAL',
            activity
        )

        messages.success(
            request,
            'MEAL activity created successfully.'
        )

        return redirect('meal:activities')

    context = {
        'form': form,
        'title': 'Create Activity',
        'cancel_url': 'meal:activities',
    }

    return render(
        request,
        'meal/activity_form.html',
        context
    )


@crud_access_required('meal')
def activity_update(request, pk):
    activity = get_object_or_404(
        Indicator,
        pk=pk
    )

    form = ActivityForm(
        request.POST or None,
        instance=activity
    )

    if form.is_valid():
        activity = _stamp_audit(
            form.save(commit=False),
            request.user
        )

        activity.save()

        audit(
            request,
            'Updated MEAL activity',
            'MEAL',
            activity
        )

        messages.success(
            request,
            'MEAL activity updated successfully.'
        )

        return redirect('meal:activities')

    context = {
        'form': form,
        'title': f'Edit {activity.code}',
        'cancel_url': 'meal:activities',
    }

    return render(
        request,
        'meal/activity_form.html',
        context
    )


@crud_access_required('meal')
def activity_delete(request, pk):
    activity = get_object_or_404(Indicator, pk=pk)
    if request.method == 'POST':
        code = activity.code
        activity.delete()
        messages.success(request, f'Activity {code} deleted.')
        return redirect('meal:activities')
    return render(request, 'meal/confirm_delete.html', {'object': activity, 'cancel_url': 'meal:activities'})


@access_required('meal')
def activity_capture(request, pk):
    activity = get_object_or_404(Indicator, pk=pk, active=True)
    form_class = PeopleActivityRecordForm if activity.is_people else NonPeopleActivityRecordForm
    try:
        selected_year = int(request.GET.get('year', timezone.localdate().year))
    except (TypeError, ValueError):
        selected_year = timezone.localdate().year
    form = form_class(request.POST or None, initial={'reporting_year': selected_year} if not request.POST else None)
    if request.method == 'POST' and form.is_valid():
        record = form.save(commit=False)
        record.indicator = activity
        record.submitted_by = request.user
        _stamp_audit(record, request.user, creating=True).save()
        audit(request, 'Submitted MEAL activity record', 'MEAL', record, f'{activity.code} ({activity.activity_type})')
        notify_group('MEAL Head', 'MEAL record awaiting review', f'{request.user} submitted {activity.code}: {activity.title}.', url=reverse('meal:records'))
        messages.success(request, 'Activity record submitted for MEAL review.')
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'record_id': record.pk})
        return redirect('meal:records')
    template = 'meal/_capture_form.html' if request.GET.get('modal') or request.headers.get('x-requested-with') == 'XMLHttpRequest' else 'meal/activity_capture.html'
    return render(request, template, {'activity': activity, 'form': form, 'is_people': activity.is_people}, status=400 if request.method == 'POST' else 200)


@access_required('meal')
def records(request):
    qs = ActivityRecord.objects.select_related(
        'indicator', 'indicator__output', 'indicator__output__objective', 'submitted_by'
    )
    status = request.GET.get('status', '')
    activity_type = request.GET.get('activity_type', '')
    year = request.GET.get('year', '')
    objective_id = request.GET.get('objective', '')
    output_id = request.GET.get('output', '')
    indicator_id = request.GET.get('indicator', '')
    query = request.GET.get('q', '').strip()

    if status in dict(ACTIVITY_STATUSES):
        qs = qs.filter(status=status)
    else:
        status = ''
    if activity_type in {'people', 'non_people'}:
        qs = qs.filter(indicator__activity_type=activity_type)
    else:
        activity_type = ''
    if year.isdigit():
        qs = qs.filter(reporting_year=int(year))
    else:
        year = ''
    if objective_id.isdigit():
        qs = qs.filter(indicator__output__objective_id=int(objective_id))
    else:
        objective_id = ''
    if output_id.isdigit():
        qs = qs.filter(indicator__output_id=int(output_id))
    else:
        output_id = ''
    if indicator_id.isdigit():
        qs = qs.filter(indicator_id=int(indicator_id))
    else:
        indicator_id = ''
    if query:
        qs = qs.filter(
            Q(indicator__code__icontains=query)
            | Q(indicator__title__icontains=query)
            | Q(indicator__indicator_text__icontains=query)
            | Q(submitted_by__first_name__icontains=query)
            | Q(submitted_by__last_name__icontains=query)
            | Q(submitted_by__username__icontains=query)
        )

    years = list(
        ActivityRecord.objects.values_list('reporting_year', flat=True)
        .distinct().order_by('-reporting_year')
    )
    return render(request, 'meal/records.html', {
        'records': qs.order_by('-reporting_year', '-reporting_month', '-created_at')[:300],
        'selected_status': status,
        'selected_activity_type': activity_type,
        'selected_year': year,
        'selected_objective': objective_id,
        'selected_output': output_id,
        'selected_indicator': indicator_id,
        'search_query': query,
        'years': years,
        'status_choices': ACTIVITY_STATUSES,
        'objectives': StrategicObjective.objects.order_by('code'),
        'outputs': Output.objects.select_related('objective').order_by('code'),
        'indicators': Indicator.objects.select_related('output').filter(active=True).order_by('code'),
    })


@crud_access_required('meal')
def record_update(request, pk):
    record = get_object_or_404(ActivityRecord, pk=pk)
    form_class = PeopleActivityRecordForm if record.indicator.is_people else NonPeopleActivityRecordForm
    form = form_class(request.POST or None, instance=record)
    if form.is_valid():
        record = _stamp_audit(form.save(commit=False), request.user)
        record.save()
        audit(request, 'Updated MEAL activity record', 'MEAL', record)
        messages.success(request, 'Record updated.')
        return redirect('meal:records')
    return render(request, 'meal/activity_capture.html', {'activity': record.indicator, 'form': form, 'is_people': record.indicator.is_people, 'editing': True})


@crud_access_required('meal')
def review_record(request, pk):
    record = get_object_or_404(ActivityRecord, pk=pk)
    if request.method == 'POST':
        new_status = request.POST.get('status')
        if new_status in dict(ACTIVITY_STATUSES):
            record.status = new_status
            record.reviewed_by = request.user
            record.reviewed_at = timezone.now()
            record.save(update_fields=['status', 'reviewed_by', 'reviewed_at'])
            audit(request, f'{new_status.title()} MEAL activity record', 'MEAL', record)
            if record.submitted_by:
                notify_user(record.submitted_by, f'MEAL record {new_status}', f'{record.indicator.code} was marked {new_status}.', level='success' if new_status == 'completed' else 'warning', url=reverse('meal:records'))
            messages.success(request, 'Record status updated.')
        return redirect('meal:records')
    return render(request, 'meal/review.html', {'record': record})


@access_required('meal')
def hierarchy_list(request):
    return render(request, 'meal/hierarchy.html', {'outcomes': StrategicObjective.objects.all()})


@access_required('meal')
def objective_list(request):
    return hierarchy_list(request)


@access_required('meal')
def output_list(request):
    return render(request, 'meal/output_list.html', {'outputs': Output.objects.select_related('objective').prefetch_related('indicators')})


@access_required('meal')
def quarterplan_list(request):
    year = _selected_tracker_year(request)
    quarter = _selected_quarter(request)
    plans = QuarterPlan.objects.filter(reporting_year=year).select_related('indicator', 'indicator__output').order_by('indicator__code', 'quarter')
    if request.GET.get('quarter') in QUARTERS:
        plans = plans.filter(quarter=quarter)
    paginator = Paginator(plans, 10)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'meal/quarterplan_list.html', {
        'plans': page_obj,
        'page_obj': page_obj,
        'plan_count': paginator.count,
        'year': year,
        'years': _tracker_years(),
        'quarter': request.GET.get('quarter', ''),
        'quarters': QUARTERS,
    })


@crud_access_required('meal')
def quarterplan_create(request):
    form = QuarterPlanForm(request.POST or None, initial={'reporting_year': _selected_tracker_year(request)})
    if form.is_valid():
        plan = _stamp_audit(form.save(commit=False), request.user, creating=True)
        plan.save()
        audit(request, 'Created MEAL quarter plan', 'MEAL', plan)
        messages.success(request, 'Quarter plan created.')
        return redirect('meal:quarterplan_list')
    return render(request, 'meal/quarter_plan_form.html', {'form': form, 'title': 'Create quarter plan', 'cancel_url': 'meal:quarterplan_list', **_quarterplan_form_context()})


@crud_access_required('meal')
def quarterplan_update(request, pk):
    plan = get_object_or_404(QuarterPlan, pk=pk)
    form = QuarterPlanForm(request.POST or None, instance=plan)
    if form.is_valid():
        plan = _stamp_audit(form.save(commit=False), request.user)
        plan.save()
        audit(request, 'Updated MEAL quarter plan', 'MEAL', plan)
        messages.success(request, 'Quarter plan updated.')
        return redirect('meal:quarterplan_list')
    return render(request, 'meal/quarter_plan_form.html', {'form': form, 'title': f'Edit quarter plan: {plan}', 'cancel_url': 'meal:quarterplan_list', **_quarterplan_form_context()})


@crud_access_required('meal')
def quarterplan_delete(request, pk):
    plan = get_object_or_404(QuarterPlan, pk=pk)
    if request.method == 'POST':
        plan.delete()
        messages.success(request, 'Quarter plan deleted.')
        return redirect('meal:quarterplan_list')
    return render(request, 'meal/confirm_delete.html', {'object': plan, 'cancel_url': 'meal:quarterplan_list'})


@access_required('meal')
def ajax_outputs(request, code):
    outputs = Output.objects.filter(objective__code=code).prefetch_related('indicators')
    return JsonResponse({'outputs': [{'id': item.pk, 'code': item.code, 'title': item.title, 'activity_count': item.indicators.count()} for item in outputs]})


@access_required('meal')
def ajax_indicators(request, code):
    indicators = Indicator.objects.filter(output__code=code, active=True)
    return JsonResponse({'activities': [{'id': item.pk, 'code': item.code, 'title': item.title, 'activity_type': item.get_activity_type_display(), 'indicator': item.indicator_text, 'target': item.target} for item in indicators]})


@access_required('meal')
def framework_detail(request, kind, code):
    model = {'objective': StrategicObjective, 'output': Output, 'activity': Indicator}.get(kind)
    if not model:
        return redirect('meal:hierarchy')
    obj = get_object_or_404(model, code=code)
    return render(request, 'meal/framework_detail.html', {'kind': kind, 'object': obj})


@crud_access_required('meal')
def framework_create(request, kind):
    form_class = {'objective': StrategicObjectiveForm, 'output': OutputForm, 'activity': IndicatorForm}.get(kind)
    if not form_class:
        return redirect('meal:hierarchy')
    form = form_class(request.POST or None)
    if form.is_valid():
        obj = _stamp_audit(form.save(commit=False), request.user, creating=True)
        obj.save()
        audit(request, f'Created MEAL {kind}', 'MEAL', obj)
        messages.success(request, f'{kind.title()} created.')
        return redirect('meal:hierarchy')
    return render(request, 'meal/framework_form.html', {'form': form, 'title': f'Create {kind}', 'cancel_url': 'meal:hierarchy'})


@crud_access_required('meal')
def framework_update(request, kind, code):
    config = {
        'objective': (StrategicObjective, StrategicObjectiveForm),
        'output': (Output, OutputForm),
        'indicator': (Indicator, IndicatorForm),
        'activity': (Indicator, IndicatorForm),
    }
    model_form = config.get(kind)
    if not model_form:
        return redirect('meal:hierarchy')
    obj = get_object_or_404(model_form[0], code=code)
    form = model_form[1](request.POST or None, instance=obj)
    if form.is_valid():
        obj = _stamp_audit(form.save(commit=False), request.user)
        obj.save()
        audit(request, f'Updated MEAL {kind}', 'MEAL', obj)
        messages.success(request, f'{kind.title()} updated.')
        return redirect('meal:hierarchy')
    return render(request, 'meal/framework_form.html', {'form': form, 'title': f'Edit {kind}', 'cancel_url': 'meal:hierarchy'})


@crud_access_required('meal')
def framework_delete(request, kind, code):
    model = {'objective': StrategicObjective, 'output': Output, 'indicator': Indicator, 'activity': Indicator}.get(kind)
    if not model:
        return redirect('meal:hierarchy')
    obj = get_object_or_404(model, code=code)
    if request.method == 'POST':
        obj.delete()
        messages.success(request, f'{kind.title()} deleted.')
        return redirect('meal:hierarchy')
    return render(request, 'meal/confirm_delete.html', {'object': obj, 'cancel_url': 'meal:hierarchy'})
