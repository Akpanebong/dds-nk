from io import BytesIO
from decimal import Decimal

from django.http import HttpResponse


NAVY = "401B5B"
TEAL = "7030A0"
PURPLE = "5B3A86"
GOLD = "D7A83D"
ORANGE = "BF651D"
LIGHT_BLUE = "F4F0F7"
LIGHT_TEAL = "FFF2CC"
LIGHT_PURPLE = "E9E1F2"
GRID = "D9E2F3"


def _number(value):
    if value is None:
        return None
    return float(value) if isinstance(value, Decimal) else value


def _safe_rows(rows, width):
    return rows or []


def _style_sheet(ws, title, description, headers, rows, chart_title=None,
                 chart_columns=None, chart_type="bar", colors=None):
    from openpyxl.chart import BarChart, Reference
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    last_col = max(len(headers), 8)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=last_col)
    ws.cell(1, 1, title)
    ws.cell(1, 1).font = Font(size=16, bold=True, color="FFFFFF")
    ws.cell(1, 1).fill = PatternFill("solid", fgColor=NAVY)
    ws.cell(1, 1).alignment = Alignment(horizontal="left")
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=last_col)
    ws.cell(2, 1, description)
    ws.cell(2, 1).font = Font(italic=True, color="44546A")
    ws.cell(2, 1).alignment = Alignment(wrap_text=True, vertical="top")
    ws.row_dimensions[2].height = 34

    header_row = 4
    for col, header in enumerate(headers, 1):
        cell = ws.cell(header_row, col, header)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=TEAL)
        cell.alignment = Alignment(wrap_text=True, horizontal="center", vertical="center")
        cell.border = Border(bottom=Side(style="medium", color=NAVY))
    ws.row_dimensions[header_row].height = 34

    for row_number, row in enumerate(_safe_rows(rows, len(headers)), 5):
        for col, value in enumerate(row, 1):
            cell = ws.cell(row_number, col, value)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            cell.border = Border(bottom=Side(style="thin", color=GRID))
            if isinstance(value, (int, float, Decimal)):
                cell.number_format = "#,##0.00"
        if row_number % 2 == 0:
            for col in range(1, len(headers) + 1):
                ws.cell(row_number, col).fill = PatternFill("solid", fgColor="F7FAFC")

    end_row = 4 + len(_safe_rows(rows, len(headers)))
    ws.freeze_panes = "A5"
    ws.auto_filter.ref = f"A4:{get_column_letter(len(headers))}{end_row}"

    widths = []
    for col in range(1, len(headers) + 1):
        longest = max([len(str(ws.cell(row, col).value or "")) for row in range(1, end_row + 1)] + [len(str(headers[col - 1]))])
        width = min(max(longest + 2, 12), 42)
        if col in (1, 2, 3):
            width = min(max(width, 22), 58)
        widths.append(width)
        ws.column_dimensions[get_column_letter(col)].width = width

    if chart_title and chart_columns and rows:
        chart = BarChart()
        chart.type = chart_type
        chart.style = 10
        chart.title = chart_title
        chart.y_axis.title = "Value"
        chart.x_axis.title = headers[0]
        chart.height = 8
        chart.width = 15
        chart.legend.position = "b"
        categories = Reference(ws, min_col=1, min_row=5, max_row=end_row)
        for index, (column, series_title) in enumerate(chart_columns):
            values = Reference(ws, min_col=column, min_row=4, max_row=end_row)
            chart.add_data(values, titles_from_data=True)
            chart.series[index].graphicalProperties.solidFill = (colors or [TEAL, GOLD])[index % len(colors or [TEAL, GOLD])]
        chart.set_categories(categories)
        chart.anchor = f"{get_column_letter(len(headers) + 2)}4"
        ws.add_chart(chart)


def _quarter_plan_rows(year):
    from .models import QuarterPlan

    plans = QuarterPlan.objects.filter(reporting_year=year).select_related("indicator", "indicator__output")
    by_indicator = {}
    for plan in plans.order_by("indicator__code", "quarter"):
        item = by_indicator.setdefault(plan.indicator_id, {
            "output": plan.indicator.output.code if plan.indicator.output else "",
            "output_title": plan.indicator.output.title if plan.indicator.output else "",
            "indicator": plan.indicator.code,
            "indicator_title": plan.indicator.title,
            "targets": {}, "budgets": {}, "expenses": {}, "results": {},
        })
        item["targets"][plan.quarter] = _number(plan.target)
        item["budgets"][plan.quarter] = _number(plan.planned_budget) or 0
        item["expenses"][plan.quarter] = _number(plan.budget_expense) or 0
        item["results"][plan.quarter] = _number(plan.workbook_result)

    rows = []
    for item in by_indicator.values():
        row = [
            item["output"], item["output_title"],
            item["indicator"], item["indicator_title"],
        ]
        for quarter in ("Q1", "Q2", "Q3", "Q4"):
            row.extend([
                item["targets"].get(quarter), item["budgets"].get(quarter, 0),
                item["expenses"].get(quarter, 0), item["results"].get(quarter),
            ])
        rows.append(row)
    return rows


def _output_rows(quarter, year):
    from .views import _group_output_rows, _quarter_rows

    return _group_output_rows(_quarter_rows(quarter, year))


def _fy_output_rows(year):
    from .views import _fy26_rows

    grouped = {}
    for row in _fy26_rows(year):
        output = row["output"]
        bucket = grouped.setdefault(output.id, {
            "code": output.code,
            "title": output.title,
            "objective": output.objective.title if output.objective else "",
            "target": 0,
            "result": 0,
            "planned_budget": 0,
            "budget_expense": 0,
        })
        for key in ("target", "result", "planned_budget", "budget_expense"):
            bucket[key] += row[key]
    rows = list(grouped.values())
    for item in rows:
        item["achievement"] = round(min(max(item["result"] / item["target"] * 100, 0), 100), 1) if item["target"] else 0
        item["variance"] = item["planned_budget"] - item["budget_expense"]
    return rows


def _build_generic_tracker_workbook(year, quarter):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment
    from .views import _quarter_rows

    output_rows = _output_rows(quarter, year)
    quarter_rows = _quarter_rows(quarter, year)
    fy_rows = _fy_output_rows(year)
    wb = Workbook()
    wb.remove(wb.active)

    quarter_headers = [
        "Output Code", "Output Title",
        "Indicator Code", "Indicator Title",
    ]
    for q in ("Q1", "Q2", "Q3", "Q4"):
        quarter_headers.extend([f"{q} Target", f"{q} Planned Budget", f"{q} Expense", f"{q} Result"])
    _style_sheet(
        wb.create_sheet("Quarter Plans"),
        f"Quarter Plans — FY{str(year)[-2:]}",
        "Quarterly targets, budgets, expenses and workbook results by indicator/activity. Values are sourced from the MEAL quarter-plan records.",
        quarter_headers,
        _quarter_plan_rows(year),
        "Quarterly targets by activity",
        [(5, "Q1 Target"), (9, "Q2 Target"), (13, "Q3 Target"), (17, "Q4 Target")],
        "bar",
        [TEAL, PURPLE, GOLD, ORANGE],
    )

    iptt_headers = [
        "Output Code", "Output Title",
        "Indicator Code", "Indicator Title",
        "Target", "Planned Budget", "Expense", "Result", "Achievement %",
    ]
    iptt_rows = [[
        item["output"].code if item["output"] else "",
        item["output"].title if item["output"] else "",
        item["code"], item["title"], item["target"], item["planned_budget"],
        item["budget_expense"], item["result"], item["achievement"],
    ] for item in quarter_rows]
    _style_sheet(
        wb.create_sheet("IPTT"),
        f"IPTT — {quarter} FY{str(year)[-2:]}",
        "Indicator Performance Tracking Table. Use this sheet to review the selected quarter's target, financial inputs and reported result by output.",
        iptt_headers,
        iptt_rows,
        f"{quarter} target versus result by output",
        [(5, "Target"), (8, "Result")],
        "bar",
        [PURPLE, GOLD],
    )

    dashboard_headers = [
        "Output Code", "Output Title", "Objective", "Target", "Result", "Achievement %",
    ]
    dashboard_rows = [[item["code"], item["title"], item["objective"], item["target"], item["result"], item["achievement"]] for item in output_rows]
    _style_sheet(
        wb.create_sheet("Output Dashboard"),
        f"{quarter} Output Dashboard — FY{str(year)[-2:]}",
        "Quarterly output performance driven from the selected IPTT view. Achievement is capped at 100% for dashboard readability.",
        dashboard_headers,
        dashboard_rows,
        f"{quarter} output target versus result",
        [(4, "Target"), (5, "Result")],
        "bar",
        [PURPLE, GOLD],
    )

    finance_headers = [
        "Output Code", "Output Title", "Planned Budget", "Expense", "Variance", "Utilisation %",
    ]
    finance_rows = [[item["code"], item["title"], item["planned_budget"], item["budget_expense"], item["variance"], round(item["budget_expense"] / item["planned_budget"] * 100, 1) if item["planned_budget"] else 0] for item in output_rows]
    _style_sheet(
        wb.create_sheet("Finance"),
        f"{quarter} Finance Dashboard — FY{str(year)[-2:]}",
        "Planned budget versus budget expense for the currently selected quarter. Variance equals planned budget less expense.",
        finance_headers,
        finance_rows,
        f"{quarter} planned budget versus expense",
        [(3, "Planned Budget"), (4, "Expense")],
        "bar",
        [TEAL, ORANGE],
    )

    fy_headers = [
        "Output Code", "Output Title", "Objective", "FY Target", "FY Result",
        "Achievement %", "Planned Budget", "Expense", "Variance",
    ]
    fy_sheet_rows = [[item["code"], item["title"], item["objective"], item["target"], item["result"], item["achievement"], item["planned_budget"], item["budget_expense"], item["variance"]] for item in fy_rows]
    _style_sheet(
        wb.create_sheet("FY Output"),
        f"FY{str(year)[-2:]} Output Dashboard",
        "Annual output performance aggregated across the selected financial year, with target, result, achievement and financial context.",
        fy_headers,
        fy_sheet_rows,
        f"FY{str(year)[-2:]} output target versus result",
        [(4, "FY Target"), (5, "FY Result")],
        "bar",
        [PURPLE, GOLD],
    )

    for ws in wb.worksheets:
        ws.sheet_view.showGridLines = False
        for row in ws.iter_rows():
            for cell in row:
                if cell.value and isinstance(cell.value, str) and len(cell.value) > 80:
                    cell.alignment = Alignment(wrap_text=True, vertical="top")
    return wb


def _template_tracker_workbook(year, quarter):
    """Refresh the supplied FY26 workbook template without losing its layout."""
    from pathlib import Path
    from openpyxl import load_workbook
    from django.conf import settings
    from .models import ActivityRecord, QuarterPlan
    from .views import QUARTER_MONTHS

    template_path = Path(settings.BASE_DIR) / "templates" / "Activity Tracker FY26.xlsx"
    workbook = load_workbook(template_path)
    iptt = workbook["IPTT"]

    plans = list(
        QuarterPlan.objects.filter(
            reporting_year=year,
        ).select_related("indicator", "indicator__output")
    )
    plan_map = {}
    for plan in plans:
        plan_map.setdefault(plan.indicator_id, {})[plan.quarter] = plan

    # Live captured records replace workbook results where available.
    records = ActivityRecord.objects.filter(reporting_year=year).select_related("indicator")
    record_values = {}
    for record in records:
        if not record.reporting_month:
            continue
        for q, months in QUARTER_MONTHS.items():
            if record.reporting_month in months:
                value = record.total_people if record.indicator.is_people else record.progress_value
                record_values[(record.indicator_id, q)] = (
                    record_values.get((record.indicator_id, q), Decimal("0"))
                    + (value or Decimal("0"))
                )

    indicators = []
    seen = set()
    for plan in sorted(plans, key=lambda item: (item.source_row or 999999, item.indicator.code)):
        if plan.indicator_id not in seen:
            indicators.append(plan.indicator)
            seen.add(plan.indicator_id)

    # source_row is populated by the template loader and keeps hierarchy rows
    # aligned with the original workbook. Fall back to the first free data row
    # for records created inside the application.
    row_by_indicator = {}
    used_rows = set()
    for plan in plans:
        if plan.source_row and plan.indicator_id not in row_by_indicator:
            row_by_indicator[plan.indicator_id] = plan.source_row
            used_rows.add(plan.source_row)
    next_row = 5
    for indicator in indicators:
        if indicator.id in row_by_indicator:
            continue
        while next_row in used_rows:
            next_row += 1
        row_by_indicator[indicator.id] = next_row
        used_rows.add(next_row)
        next_row += 1

    # Clear data cells only; the template's hierarchy formatting and merged
    # sections remain untouched.
    for row_number in range(5, iptt.max_row + 1):
        for column in range(2, 25):
            cell = iptt.cell(row_number, column)
            if cell.__class__.__name__ != "MergedCell":
                cell.value = None

    output_rows = {}
    for indicator in indicators:
        row_number = row_by_indicator[indicator.id]
        output = indicator.output
        output_key = output.id if output else None
        output_rows.setdefault(output_key, []).append(row_number)
        iptt.cell(row_number, 2).value = f"Output {output.code}: {output.title}" if output else "Unassigned output"
        iptt.cell(row_number, 3).value = f"{indicator.code}: {indicator.title}"

        indicator_plans = plan_map.get(indicator.id, {})
        for index, q in enumerate(("Q1", "Q2", "Q3", "Q4")):
            plan = indicator_plans.get(q)
            target_col = 4 + index
            budget_col = 8 + index * 2
            expense_col = budget_col + 1
            result_col = 16 + index
            iptt.cell(row_number, target_col).value = _number(plan.target) if plan else None
            iptt.cell(row_number, budget_col).value = _number(plan.planned_budget) if plan else None
            iptt.cell(row_number, expense_col).value = _number(plan.budget_expense) if plan else None
            live_result = record_values.get((indicator.id, q))
            iptt.cell(row_number, result_col).value = (
                _number(live_result) if live_result is not None
                else (_number(plan.workbook_result) if plan else None)
            )

        annual_plans = list(indicator_plans.values())
        iptt.cell(row_number, 20).value = sum((_number(item.planned_budget) or 0) for item in annual_plans)
        iptt.cell(row_number, 21).value = sum((_number(item.target) or 0) for item in annual_plans)
        iptt.cell(row_number, 22).value = f"=SUM(P{row_number}:S{row_number})"

    # Output-level finance totals are displayed on the first indicator row,
    # matching the attached workbook's hierarchy layout.
    for rows in output_rows.values():
        first_row, last_row = min(rows), max(rows)
        iptt.cell(first_row, 23).value = f"=SUM(H{first_row}:H{last_row},J{first_row}:J{last_row},L{first_row}:L{last_row},N{first_row}:N{last_row})"
        iptt.cell(first_row, 24).value = f"=SUM(I{first_row}:I{last_row},K{first_row}:K{last_row},M{first_row}:M{last_row},O{first_row}:O{last_row})"

    # Keep the selected quarter visible in the workbook title and tab names.
    output_sheet = workbook["Q1 Output Dash_Board"]
    finance_sheet = workbook["Finance Q1"]
    output_sheet.title = f"{quarter} Output Dash_Board"
    finance_sheet.title = f"Finance {quarter}"
    for sheet in workbook.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                if isinstance(cell.value, str):
                    cell.value = cell.value.replace("Q1 Output Dash_Board", f"{quarter} Output Dash_Board")
                    cell.value = cell.value.replace("Finance Q1", f"Finance {quarter}")
    output_sheet["A1"] = f"FY{str(year)[-2:]} | {quarter} OUTPUT DASHBOARD"
    finance_sheet["A1"] = f"FY {str(year)[-2:]}"
    finance_sheet["B1"] = f"PLANNED BUDGET VS EXPENSE — {quarter}"
    workbook.properties.title = f"Activity Tracker FY{str(year)[-2:]}"
    workbook.properties.subject = "MEAL activity tracker, output dashboard and finance workbook"
    workbook.properties.creator = "DDS-NK MEAL"
    return workbook


def _database_tracker_workbook(year, quarter):
    """Build every visible workbook value from the current MEAL database."""
    from collections import defaultdict
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from .models import ActivityRecord, Indicator, Output, QuarterPlan, StrategicObjective
    from .views import QUARTER_MONTHS

    indicators = list(
        Indicator.objects.filter(active=True).select_related("output", "output__objective").order_by("code")
    )
    plans = list(
        QuarterPlan.objects.filter(reporting_year=year, indicator__active=True)
        .select_related("indicator", "indicator__output", "indicator__output__objective")
    )
    plans_by_indicator = defaultdict(dict)
    for plan in plans:
        plans_by_indicator[plan.indicator_id][plan.quarter] = plan

    live_results = defaultdict(lambda: defaultdict(Decimal))
    annual_records = defaultdict(Decimal)
    for record in ActivityRecord.objects.filter(reporting_year=year).select_related("indicator"):
        value = record.total_people if record.indicator.is_people else record.progress_value
        value = value or Decimal("0")
        annual_records[record.indicator_id] += value
        if record.reporting_month:
            for name, months in QUARTER_MONTHS.items():
                if record.reporting_month in months:
                    live_results[record.indicator_id][name] += value

    def metric(indicator, name, attribute):
        plan = plans_by_indicator[indicator.id].get(name)
        return _number(getattr(plan, attribute)) if plan else None

    indicator_rows = []
    for indicator in indicators:
        quarter_values = {}
        for name in ("Q1", "Q2", "Q3", "Q4"):
            quarter_values[name] = {
                "target": metric(indicator, name, "target"),
                "planned": metric(indicator, name, "planned_budget"),
                "expense": metric(indicator, name, "budget_expense"),
                "result": (
                    _number(live_results[indicator.id][name])
                    if name in live_results[indicator.id]
                    else metric(indicator, name, "workbook_result")
                ),
            }
        annual_target = sum((item["target"] or 0) for item in quarter_values.values())
        annual_budget = sum((item["planned"] or 0) for item in quarter_values.values())
        annual_result = (
            _number(annual_records[indicator.id])
            if indicator.id in annual_records
            else sum((item["result"] or 0) for item in quarter_values.values())
        )
        indicator_rows.append({
            "indicator": indicator,
            "output": indicator.output,
            "objective": indicator.output.objective if indicator.output else None,
            "quarters": quarter_values,
            "annual_target": annual_target,
            "annual_budget": annual_budget,
            "annual_result": annual_result,
        })

    grouped = defaultdict(list)
    for row in indicator_rows:
        if row["output"]:
            grouped[row["output"].id].append(row)

    output_rows = []
    for output in Output.objects.select_related("objective").order_by("code"):
        items = grouped.get(output.id, [])
        target = sum((item["quarters"][quarter]["target"] or 0) for item in items)
        result = sum((item["quarters"][quarter]["result"] or 0) for item in items)
        planned = sum((item["quarters"][quarter]["planned"] or 0) for item in items)
        expense = sum((item["quarters"][quarter]["expense"] or 0) for item in items)
        fy_target = sum(item["annual_target"] or 0 for item in items)
        fy_result = sum(item["annual_result"] or 0 for item in items)
        fy_planned = sum(item["annual_budget"] or 0 for item in items)
        fy_expense = sum(
            (item["quarters"][q]["expense"] or 0)
            for item in items for q in ("Q1", "Q2", "Q3", "Q4")
        )
        output_rows.append({
            "code": output.code, "title": output.title,
            "description": output.description,
            "objective": output.objective.title if output.objective else "",
            "target": target, "result": result, "planned_budget": planned,
            "budget_expense": expense, "variance": planned - expense,
            "achievement": round(min(max(result / target * 100, 0), 100), 1) if target else 0,
            "fy_target": fy_target, "fy_result": fy_result,
            "fy_planned": fy_planned, "fy_expense": fy_expense,
            "fy_variance": fy_planned - fy_expense,
            "fy_achievement": round(min(max(fy_result / fy_target * 100, 0), 100), 1) if fy_target else 0,
        })

    wb = Workbook()
    wb.remove(wb.active)

    # IPTT: hierarchy labels and metrics are all generated from DB rows.
    iptt_headers = ["Output", "Indicator"]
    for name in ("Q1", "Q2", "Q3", "Q4"):
        iptt_headers.extend([f"{name} Target", f"{name} Planned Budget", f"{name} Expense"])
    iptt_headers.extend(["FY Target", "FY Result", "FY Planned Budget", "FY Expense", "FY Variance"])
    iptt_rows = []
    current_objective_id = object()
    for row in indicator_rows:
        indicator = row["indicator"]
        output = row["output"]
        objective = row["objective"]
        if objective and objective.id != current_objective_id:
            iptt_rows.append([f"{objective.code}: {objective.title}"] + [None] * 22)
            current_objective_id = objective.id
        output_label = f"{output.code}: {output.title}" if output else "Unassigned output"
        if output and output.description:
            output_label += f"\n{output.description}"
        indicator_label = f"{indicator.code}: {indicator.title}"
        if indicator.indicator_text:
            indicator_label += f"\n{indicator.indicator_text}"
        values = [output_label, indicator_label]
        for name in ("Q1", "Q2", "Q3", "Q4"):
            values.extend([
                row["quarters"][name]["target"], row["quarters"][name]["planned"],
                row["quarters"][name]["expense"],
            ])
        values.extend([
            row["annual_target"], row["annual_result"], row["annual_budget"],
            sum((row["quarters"][q]["expense"] or 0) for q in ("Q1", "Q2", "Q3", "Q4")),
            row["annual_budget"] - sum((row["quarters"][q]["expense"] or 0) for q in ("Q1", "Q2", "Q3", "Q4")),
        ])
        # Keep quarterly results directly after each quarter's budget block,
        # matching the attached IPTT's compact layout.
        values = values[:2]
        for name in ("Q1", "Q2", "Q3", "Q4"):
            values.extend([
                row["quarters"][name]["target"],
                row["quarters"][name]["planned"],
                row["quarters"][name]["expense"],
                row["quarters"][name]["result"],
            ])
        values.extend([
            row["annual_budget"], row["annual_target"], row["annual_result"],
            sum((row["quarters"][q]["planned"] or 0) for q in ("Q1", "Q2", "Q3", "Q4")),
            sum((row["quarters"][q]["expense"] or 0) for q in ("Q1", "Q2", "Q3", "Q4")),
        ])
        iptt_rows.append(values)
    iptt = wb.create_sheet("IPTT")
    iptt.merge_cells("B1:C1")
    iptt.merge_cells("D1:G1")
    iptt.merge_cells("H1:O1")
    iptt.merge_cells("P1:S1")
    iptt.merge_cells("T1:X1")
    iptt["B1"] = "Results Hierarchy"
    iptt["D1"] = "Quarterly Targets"
    iptt["H1"] = "Quarterly Budget"
    iptt["P1"] = "Quarterly Results"
    iptt["T1"] = f"FY{str(year)[-2:]}"
    headers = ["Output", "Indicator", "Q1 Target", "Q1 Planned Budget", "Q1 Expense", "Q1 Result", "Q2 Target", "Q2 Planned Budget", "Q2 Expense", "Q2 Result", "Q3 Target", "Q3 Planned Budget", "Q3 Expense", "Q3 Result", "Q4 Target", "Q4 Planned Budget", "Q4 Expense", "Q4 Result", "FY Budget", "FY Target", "FY Result", "FY Planned Budget", "FY Expense"]
    for col, value in enumerate(headers, 2):
        iptt.cell(2, col, value)
    header_fill = PatternFill("solid", fgColor=NAVY)
    subheader_fill = PatternFill("solid", fgColor=TEAL)
    thin = Side(style="thin", color="FFFFFF")
    for row in (1, 2):
        for cell in iptt[row][1:24]:
            cell.fill = header_fill if row == 1 else subheader_fill
            cell.font = Font(name="Calibri", size=10 if row == 1 else 9, bold=True, color="FFFFFF")
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = Border(bottom=thin)
    for row_number, values in enumerate(iptt_rows, 3):
        if values[0] and all(value is None for value in values[1:]):
            iptt.merge_cells(start_row=row_number, start_column=2, end_row=row_number, end_column=24)
            cell = iptt.cell(row_number, 2, values[0])
            cell.fill = PatternFill("solid", fgColor="EADCF4")
            cell.font = Font(name="Calibri", size=10, bold=True, color=NAVY)
            cell.alignment = Alignment(vertical="center", wrap_text=True)
            iptt.row_dimensions[row_number].height = 24
            continue
        for col, value in enumerate(values, 2):
            cell = iptt.cell(row_number, col, value)
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            cell.border = Border(bottom=Side(style="thin", color="D9D2E9"))
            if isinstance(value, (int, float, Decimal)):
                cell.number_format = "#,##0.00"
        if row_number % 2 == 0:
            for col in range(2, 25):
                iptt.cell(row_number, col).fill = PatternFill("solid", fgColor="F8F5FA")
    for col, width in {"B": 34, "C": 48, "D": 13, "E": 16, "F": 13, "G": 13, "H": 13, "I": 16, "J": 13, "K": 13, "L": 13, "M": 16, "N": 13, "O": 13, "P": 13, "Q": 16, "R": 13, "S": 13, "T": 14, "U": 14, "V": 14, "W": 16, "X": 14}.items():
        iptt.column_dimensions[col].width = width
    iptt.row_dimensions[1].height = 26
    iptt.row_dimensions[2].height = 34
    iptt.freeze_panes = "D3"
    iptt.auto_filter.ref = f"B2:X{max(2, iptt.max_row)}"

    # Dashboard and finance sheets use the same dynamic output rows.
    dashboard_headers = ["Output Code", "Output Title", "Output Description", "Objective", "Target", "Result", "Achievement %"]
    dashboard_rows = [[item["code"], item["title"], item["description"], item["objective"], item["target"], item["result"], item["achievement"]] for item in output_rows]
    _style_sheet(wb.create_sheet(f"{quarter} Output Dash_Board"), f"FY{str(year)[-2:]} | {quarter} OUTPUT DASHBOARD", f"{quarter} — FY{str(year)[-2:]}", dashboard_headers, dashboard_rows, f"{quarter} target versus result", [(5, "Target"), (6, "Result")], colors=[PURPLE, GOLD])

    finance_headers = ["Output Code", "Output Title", "Output Description", "Planned Budget", "Expense", "Variance", "Utilisation %"]
    finance_rows = [[item["code"], item["title"], item["description"], item["planned_budget"], item["budget_expense"], item["variance"], round(item["budget_expense"] / item["planned_budget"] * 100, 1) if item["planned_budget"] else 0] for item in output_rows]
    _style_sheet(wb.create_sheet(f"Finance {quarter}"), f"FY {str(year)[-2:]}", f"PLANNED BUDGET VS EXPENSE — {quarter}", finance_headers, finance_rows, f"{quarter} planned budget versus expense", [(4, "Planned Budget"), (5, "Expense")], colors=[TEAL, ORANGE])

    fy_headers = ["Output Code", "Output Title", "Output Description", "Objective", "FY Target", "FY Result", "Achievement %", "Planned Budget", "Expense", "Variance"]
    fy_rows = [[item["code"], item["title"], item["description"], item["objective"], item["fy_target"], item["fy_result"], item["fy_achievement"], item["fy_planned"], item["fy_expense"], item["fy_variance"]] for item in output_rows]
    _style_sheet(wb.create_sheet(f"FY{str(year)[-2:]} Output Dash_Board"), f"FY{str(year)[-2:]} OUTPUT DASHBOARD", f"FY{str(year)[-2:]}", fy_headers, fy_rows, f"FY{str(year)[-2:]} target versus result", [(5, "FY Target"), (6, "FY Result")], colors=[PURPLE, GOLD])

    for sheet in wb.worksheets:
        sheet.sheet_view.showGridLines = False
        sheet.freeze_panes = "A5"
        for row in sheet.iter_rows():
            for cell in row:
                if cell.value is not None:
                    cell.alignment = Alignment(wrap_text=True, vertical="top")
    wb.properties.title = f"Activity Tracker FY{str(year)[-2:]}"
    wb.properties.subject = "Database-generated MEAL activity tracker"
    wb.properties.creator = "DDS-NK MEAL"
    return wb


def build_tracker_workbook(year, quarter):
    return _database_tracker_workbook(year, quarter)


def tracker_workbook_response(year, quarter):
    from openpyxl import Workbook

    workbook = build_tracker_workbook(year, quarter)
    stream = BytesIO()
    workbook.save(stream)
    stream.seek(0)
    response = HttpResponse(
        stream.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="Activity Tracker FY{str(year)[-2:]}.xlsx"'
    return response
