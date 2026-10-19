from django.contrib import admin
from django.db.models import Sum
from django.utils.html import format_html

from .models import (
    Supplier,
    Product,
    ProcurementPlan,
    ProcurementPlanItem,
    Requisition,
    RequisitionItem,
    RFQ,
    RFQSendLog,
    PurchaseOrder,
    SupplierSpendReport,
)
from .project_models import Project, ProjectBudget


# ============================================================
# ADMIN SITE CONFIGURATION
# ============================================================

admin.site.site_header = "DDS-NK | Procurement Administration"
admin.site.site_title = "DDS-NK Procurement Admin"
admin.site.index_title = "Procurement Management"


# ============================================================
# SHARED ADMIN UTILITIES
# ============================================================

class ReadOnlyAuditAdminMixin:
    """Make common audit timestamps read-only where available."""

    readonly_fields = ()

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))

        for field_name in ("created_at", "updated_at", "last_updated"):
            if any(
                field.name == field_name
                for field in self.model._meta.get_fields()
            ):
                if field_name not in readonly:
                    readonly.append(field_name)

        return tuple(readonly)


# ============================================================
# INLINE ADMIN
# ============================================================

class ProcurementPlanItemInline(admin.TabularInline):
    model = ProcurementPlanItem
    extra = 0
    show_change_link = True
    fields = (
        "product",
        "description",
        "qty",
        "est_unit_cost",
        "unit_measure",
        "delivery_date",
    )


class RequisitionItemInline(admin.TabularInline):
    model = RequisitionItem
    extra = 0
    show_change_link = True
    fields = (
        "procurement_item",
        "description",
        "unit_measure",
        "qty",
        "unit_price",
        "delivery_date",
    )


class RFQSendLogInline(admin.TabularInline):
    model = RFQSendLog
    extra = 0
    show_change_link = True
    fields = (
        "supplier",
        "amount",
        "awarded_amount",
        "request_id",
        "date_sent",
    )
    readonly_fields = ("date_sent",)


class PurchaseOrderInline(admin.TabularInline):
    model = PurchaseOrder
    extra = 0
    show_change_link = True
    fields = (
        "po_number",
        "supplier",
        "final_amount",
        "issue_date",
        "due_date",
        "sent",
    )


class SupplierSpendReportInline(admin.TabularInline):
    model = SupplierSpendReport
    extra = 0
    show_change_link = True
    fields = (
        "purchase_order",
        "requisition",
        "total_spent",
        "invoice_no",
        "invoice_date",
        "invoice_amount",
        "payment_status",
    )
    readonly_fields = ("total_spent", "last_updated")


# ============================================================
# SUPPLIERS
# ============================================================

@admin.register(Supplier)
class SupplierAdmin(ReadOnlyAuditAdminMixin, admin.ModelAdmin):
    list_display = (
        "supplier_code",
        "name",
        "supplier_type",
        "category",
        "contact_person",
        "email",
        "phone",
        "prequalified_status",
        "active_status",
        "rating",
    )

    list_display_links = ("supplier_code", "name")

    list_filter = (
        "supplier_type",
        "category",
        "prequalified",
        "active",
    )

    search_fields = (
        "supplier_code",
        "name",
        "title",
        "category",
        "contact_person",
        "email",
        "phone",
        "tin_number",
    )

    ordering = ("name",)
    list_per_page = 25
    date_hierarchy = None
    list_select_related = ()

    readonly_fields = ("slug", "supplier_code")

    fieldsets = (
        ("Supplier Identification", {
            "fields": (
                "name",
                "supplier_code",
                "slug",
                "supplier_type",
                "title",
                "category",
            )
        }),
        ("Contact Information", {
            "fields": (
                "contact_person",
                "email",
                "phone",
                "address",
            )
        }),
        ("Compliance and Documentation", {
            "fields": (
                "tin_number",
                "documents",
            )
        }),
        ("Qualification and Approval", {
            "fields": (
                "prequalified",
                "active",
                "rating",
            )
        }),
        ("Internal Records", {
            "fields": ("notes",),
            "classes": ("collapse",),
        }),
    )

    inlines = (
        # Related supplier records are available through their own
        # admin pages; avoid exposing unrelated records here.
    )

    @admin.display(description="Prequalified", boolean=True, ordering="prequalified")
    def prequalified_status(self, obj):
        return obj.prequalified

    @admin.display(description="Active", boolean=True, ordering="active")
    def active_status(self, obj):
        return obj.active


# ============================================================
# PRODUCTS
# ============================================================

@admin.register(Product)
class ProductAdmin(ReadOnlyAuditAdminMixin, admin.ModelAdmin):
    list_display = (
        "code",
        "name",
        "category",
        "unit",
        "est_unit_cost",
        "supplier",
        "active_status",
        "updated_at",
    )

    list_display_links = ("code", "name")

    list_filter = (
        "active",
        "category",
        "unit",
        "supplier",
    )

    search_fields = (
        "code",
        "name",
        "description",
        "other_category",
        "supplier__name",
        "supplier__supplier_code",
    )

    autocomplete_fields = ("supplier",)
    list_select_related = ("supplier",)
    ordering = ("name",)
    list_per_page = 25
    readonly_fields = ("code", "created_at", "updated_at")

    fieldsets = (
        ("Product Identification", {
            "fields": (
                "code",
                "name",
                "description",
            )
        }),
        ("Classification and Unit", {
            "fields": (
                "category",
                "other_category",
                "unit",
            )
        }),
        ("Pricing and Supplier", {
            "fields": (
                "est_unit_cost",
                "supplier",
            )
        }),
        ("Availability", {
            "fields": (
                "active",
                "created_at",
                "updated_at",
            )
        }),
    )

    @admin.display(description="Active", boolean=True, ordering="active")
    def active_status(self, obj):
        return obj.active


# ============================================================
# PROJECTS AND BUDGETS
# ============================================================

@admin.register(Project)
class ProjectAdmin(ReadOnlyAuditAdminMixin, admin.ModelAdmin):
    list_display = ("__str__",)
    search_fields = ("name",)
    ordering = ("name",)
    list_per_page = 25


@admin.register(ProjectBudget)
class ProjectBudgetAdmin(ReadOnlyAuditAdminMixin, admin.ModelAdmin):
    list_display = (
        "__str__",
        "project",
        "fiscal_year",
        "period",
        "budget_amount",
    )

    list_filter = (
        "fiscal_year",
        "period",
    )

    search_fields = (
        "project__name",
        "fiscal_year",
    )

    list_select_related = ("project",)
    ordering = ("project", "fiscal_year", "period")
    list_per_page = 25


# ============================================================
# PROCUREMENT PLANS
# ============================================================

@admin.register(ProcurementPlan)
class ProcurementPlanAdmin(ReadOnlyAuditAdminMixin, admin.ModelAdmin):
    list_display = (
        "number",
        "project",
        "fiscal_year",
        "budget_period",
        "total_amount",
        "status_badge",
        "requester",
        "created_at",
    )

    list_display_links = ("number",)

    list_filter = (
        "status",
        "fiscal_year",
        "budget_period",
        "project",
    )

    search_fields = (
        "number",
        "project__name",
        "requester__username",
        "requester__first_name",
        "requester__last_name",
        "donor",
    )

    autocomplete_fields = (
        "requester",
        "project",
        "project_budget",
        "reviewed_by",
        "approved_by",
        "rejected_by",
    )

    list_select_related = (
        "project",
        "requester",
        "project_budget",
        "reviewed_by",
        "approved_by",
        "rejected_by",
    )

    ordering = ("-created_at",)
    list_per_page = 25
    date_hierarchy = "created_at"
    inlines = (ProcurementPlanItemInline,)

    readonly_fields = (
        "number",
        "slug",
        "total_amount",
        "reviewed_at",
        "approved_at",
        "rejected_at",
        "created_at",
        "updated_at",
        "progress_display",
        "remaining_budget_display",
    )

    fieldsets = (
        ("Plan Identification", {
            "fields": (
                "number",
                "slug",
                "project",
                "requester",
                "donor",
            )
        }),
        ("Budget and Financial Details", {
            "fields": (
                "fiscal_year",
                "budget_period",
                "project_budget",
                "budget",
                "total_amount",
                "remaining_budget_display",
            )
        }),
        ("Workflow", {
            "fields": (
                "status",
                "progress_display",
                "reviewed_by",
                "reviewed_at",
                "approved_by",
                "approved_at",
                "rejected_by",
                "rejected_at",
                "rejection_reason",
            )
        }),
        ("System Records", {
            "fields": (
                "created_at",
                "updated_at",
            ),
            "classes": ("collapse",),
        }),
    )

    @admin.display(description="Workflow status", ordering="status")
    def status_badge(self, obj):
        colors = {
            "draft": ("#475569", "#f1f5f9"),
            "submitted": ("#c2410c", "#fff7ed"),
            "review_approved": ("#0369a1", "#e0f2fe"),
            "review_rejected": ("#b91c1c", "#fef2f2"),
            "approved": ("#166534", "#dcfce7"),
            "ed_rejected": ("#b91c1c", "#fef2f2"),
        }

        foreground, background = colors.get(
            obj.status, ("#475569", "#f1f5f9")
        )

        return format_html(
            '<span style="display:inline-block;padding:4px 9px;'
            'border-radius:20px;font-weight:600;font-size:12px;'
            'color:{};background:{};">{}</span>',
            foreground,
            background,
            obj.get_status_display(),
        )

    @admin.display(description="Workflow progress")
    def progress_display(self, obj):
        return f"{obj.progress_percentage}% â€” {obj.progress_label}"

    @admin.display(description="Remaining budget")
    def remaining_budget_display(self, obj):
        return f"{obj.remaining_budget:,.2f}"


# ============================================================
# PROCUREMENT PLAN ITEMS
# ============================================================

@admin.register(ProcurementPlanItem)
class ProcurementPlanItemAdmin(ReadOnlyAuditAdminMixin, admin.ModelAdmin):
    list_display = (
        "procurement",
        "product",
        "description",
        "qty",
        "est_unit_cost",
        "line_total_display",
        "unit_measure",
        "delivery_date",
    )

    list_filter = (
        "delivery_date",
        "product__category",
    )

    search_fields = (
        "procurement__number",
        "procurement__project__name",
        "product__name",
        "product__code",
        "description",
    )

    autocomplete_fields = ("procurement", "product")
    list_select_related = ("procurement", "product")
    ordering = ("-delivery_date",)
    list_per_page = 25

    @admin.display(description="Line total", ordering="est_unit_cost")
    def line_total_display(self, obj):
        return f"{obj.line_total():,.2f}"


# ============================================================
# REQUISITIONS
# ============================================================

@admin.register(Requisition)
class RequisitionAdmin(ReadOnlyAuditAdminMixin, admin.ModelAdmin):
    list_display = (
        "number",
        "procurement",
        "issued_by",
        "date",
        "total",
        "awarded_amount",
        "status",
        "approval_indicator",
    )

    list_display_links = ("number",)

    list_filter = (
        "status",
        "date",
    )

    search_fields = (
        "number",
        "activity_name",
        "procurement__number",
        "procurement__project__name",
        "issued_by__username",
        "issued_by__first_name",
        "issued_by__last_name",
    )

    autocomplete_fields = ("procurement", "issued_by")
    list_select_related = ("procurement", "issued_by")
    ordering = ("-created_at",)
    date_hierarchy = "date"
    list_per_page = 25
    inlines = (RequisitionItemInline,)

    readonly_fields = (
        "slug",
        "total",
        "approval_indicator",
    )

    @admin.display(description="Approval progress")
    def approval_indicator(self, obj):
        steps = (
            ("Reviewed", bool(obj.reviewed_by)),
            ("Checked", bool(obj.checked_by)),
            ("Approved", bool(obj.approved_by)),
        )

        completed = sum(done for _, done in steps)
        return f"{completed}/3 approval steps completed"


# ============================================================
# REQUISITION ITEMS
# ============================================================

@admin.register(RequisitionItem)
class RequisitionItemAdmin(admin.ModelAdmin):
    list_display = (
        "po",
        "description",
        "procurement_item",
        "qty",
        "unit_price",
        "line_total_display",
        "delivery_date",
    )

    list_filter = ("delivery_date",)

    search_fields = (
        "po__number",
        "description",
        "procurement_item__description",
        "procurement_item__product__name",
    )

    autocomplete_fields = ("po", "procurement_item")
    list_select_related = ("po", "procurement_item")
    ordering = ("-id",)
    list_per_page = 25

    @admin.display(description="Line total")
    def line_total_display(self, obj):
        return f"{obj.line_total():,.2f}"


# ============================================================
# REQUESTS FOR QUOTATION
# ============================================================

@admin.register(RFQ)
class RFQAdmin(ReadOnlyAuditAdminMixin, admin.ModelAdmin):
    list_display = (
        "reference_no",
        "req",
        "date_issued",
        "deadline",
        "status",
        "supplier_count",
    )

    list_display_links = ("reference_no",)

    list_filter = (
        "status",
        "date_issued",
        "deadline",
    )

    search_fields = (
        "reference_no",
        "req__number",
        "req__procurement__number",
        "req__procurement__project__name",
        "supplier__name",
        "supplier__supplier_code",
    )

    autocomplete_fields = ("req", "supplier")
    filter_horizontal = ("supplier",)
    list_select_related = ("req",)
    ordering = ("-date_issued",)
    list_per_page = 25
    inlines = (RFQSendLogInline,)

    readonly_fields = ("slug",)

    @admin.display(description="Suppliers")
    def supplier_count(self, obj):
        return obj.supplier.count()


# ============================================================
# RFQ SEND LOGS
# ============================================================

@admin.register(RFQSendLog)
class RFQSendLogAdmin(admin.ModelAdmin):
    list_display = (
        "rfq",
        "supplier",
        "amount",
        "awarded_amount",
        "date_sent",
        "request_id",
    )

    list_filter = (
        "date_sent",
        "rfq__status",
    )

    search_fields = (
        "rfq__reference_no",
        "supplier__name",
        "supplier__supplier_code",
        "request_id",
    )

    autocomplete_fields = ("rfq", "supplier")
    list_select_related = ("rfq", "supplier")
    ordering = ("-date_sent",)
    date_hierarchy = "date_sent"
    list_per_page = 25
    readonly_fields = ("date_sent",)

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj is not None:
            fields.extend(("rfq", "supplier"))
        return tuple(fields)


# ============================================================
# PURCHASE ORDERS
# ============================================================

@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(ReadOnlyAuditAdminMixin, admin.ModelAdmin):
    list_display = (
        "po_number",
        "supplier",
        "rfq",
        "requisition",
        "procurement_plan",
        "final_amount",
        "issue_date",
        "due_date",
        "sent_status",
    )

    list_display_links = ("po_number",)

    list_filter = (
        "sent",
        "issue_date",
        "due_date",
    )

    search_fields = (
        "po_number",
        "supplier__name",
        "supplier__supplier_code",
        "rfq__reference_no",
        "requisition__number",
        "procurement_plan__number",
        "procurement_plan__project__name",
    )

    autocomplete_fields = (
        "send_log",
        "supplier",
        "rfq",
        "requisition",
        "procurement_plan",
    )

    list_select_related = (
        "send_log",
        "supplier",
        "rfq",
        "requisition",
        "procurement_plan",
    )

    ordering = ("-created_at",)
    date_hierarchy = "issue_date"
    list_per_page = 25

    readonly_fields = (
        "slug",
        "created_at",
    )

    fieldsets = (
        ("Order Identification", {
            "fields": (
                "po_number",
                "slug",
                "send_log",
                "supplier",
            )
        }),
        ("Procurement References", {
            "fields": (
                "rfq",
                "requisition",
                "procurement_plan",
            )
        }),
        ("Financial and Delivery Details", {
            "fields": (
                "final_amount",
                "issue_date",
                "due_date",
                "remarks",
            )
        }),
        ("Dispatch and Documentation", {
            "fields": (
                "sent",
                "pdf",
                "created_at",
            )
        }),
    )

    @admin.display(description="Sent", boolean=True, ordering="sent")
    def sent_status(self, obj):
        return obj.sent


# ============================================================
# SUPPLIER SPEND REPORTS
# ============================================================

@admin.register(SupplierSpendReport)
class SupplierSpendReportAdmin(ReadOnlyAuditAdminMixin, admin.ModelAdmin):
    list_display = (
        "supplier",
        "purchase_order",
        "requisition",
        "total_spent",
        "invoice_no",
        "invoice_date",
        "invoice_amount",
        "payment_status",
        "last_updated",
    )

    list_filter = (
        "payment_status",
        "invoice_date",
        "last_updated",
    )

    search_fields = (
        "supplier__name",
        "supplier__supplier_code",
        "purchase_order__po_number",
        "requisition__number",
        "invoice_no",
    )

    autocomplete_fields = (
        "supplier",
        "purchase_order",
        "requisition",
    )

    list_select_related = (
        "supplier",
        "purchase_order",
        "requisition",
    )

    ordering = ("-last_updated",)
    date_hierarchy = "last_updated"
    list_per_page = 25

    readonly_fields = (
        "slug",
        "total_spent",
        "last_updated",
    )

    fieldsets = (
        ("Supplier and Transaction", {
            "fields": (
                "supplier",
                "purchase_order",
                "requisition",
            )
        }),
        ("Invoice Information", {
            "fields": (
                "invoice_no",
                "invoice_date",
                "invoice_amount",
                "payment_status",
            )
        }),
        ("Spend Summary", {
            "fields": (
                "total_spent",
                "last_updated",
                "slug",
            )
        }),
    )
