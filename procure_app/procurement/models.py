from django.conf import settings
from decimal import Decimal
from uuid import uuid4
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
from django.db.models import DecimalField, F, Sum
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.urls import reverse
from django.utils import timezone
from core.model_audit_stamp import AuditStampedModel, ApprovalWorkflowModel
from core.slug import unique_slug
from .project_models import Project, ProjectBudget


class Supplier(AuditStampedModel):
    SUPPLIER_TYPES = [("individual", "Individual"), ("organisation", "Organisation"),]
    # Identification
    slug = models.SlugField(max_length=255, unique=True, editable=False,)
    supplier_code = models.CharField(max_length=30, unique=True, blank=True, db_index=True,
                                     help_text="Internal DDS-NK supplier reference.")
    supplier_type = models.CharField(max_length=20, choices=SUPPLIER_TYPES, default="organisation",)
    name = models.CharField(max_length=255, help_text="Supplier's business or individual name.",)
    title = models.CharField(max_length=255, blank=True, help_text="Optional business title or description.",)
    category = models.CharField(max_length=100, blank=True, db_index=True, help_text="Goods or services supplied.",)
    # Contact information
    contact_person = models.CharField(max_length=255, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    address = models.TextField(blank=True)

    # Compliance and documentation
    tin_number = models.CharField(max_length=64, blank=True, db_index=True,)
    documents = models.FileField(upload_to="suppliers/docs/", blank=True, null=True,)

    # Procurement qualification and approval
    prequalified = models.BooleanField(default=False)
    active = models.BooleanField(default=False,
        help_text="Approved and active for procurement transactions.", db_index=True,)

    # Performance and internal records
    rating = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True,
                                 validators=[MinValueValidator(0), MaxValueValidator(5)])
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Supplier"
        verbose_name_plural = "Suppliers"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(self, self.name)
        if not self.supplier_code:
            self.supplier_code = f"SUP-{unique_slug(self, self.name)[:8].upper()}"

        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


ASSET_CATEGORIES = (
    ('VEHICLE', 'Vehicle'),
    ('MOTORCYCLE', 'Motorcycle'),
    ('ICT', 'ICT Equipment'),
    ('FURNITURE', 'Furniture'),
    ('OFFICE', 'Office Equipment'),
    ('LAND', 'Land'),
    ('BUILDING', 'Building'),
    ('PLANT', 'Plant & Machinery'),
    ('OTHER', 'Other'),
)


class Product(models.Model):
    UNIT_CHOICES = (
        ('piece', 'Piece'), ('set', 'Set'), ('pack', 'Pack'), ('box', 'Box'),
        ('litre', 'Litre'), ('kg', 'Kilogram'), ('day', 'Day'), ('service', 'Service'),
    )
    code = models.CharField(max_length=40, unique=True, blank=True, db_index=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    est_unit_cost = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    unit = models.CharField(max_length=20, choices=UNIT_CHOICES, default='piece')
    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name='products')
    category = models.CharField(max_length=50, choices=ASSET_CATEGORIES, blank=True, null=True, )
    other_category = models.CharField(max_length=120, blank=True, default='')
    active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('name',)
        indexes = [models.Index(fields=('category', 'active')), models.Index(fields=('supplier', 'active'))]

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = f"PRD-{unique_slug(self, self.name)[:8].upper()}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.code} — {self.name}'


# Backwards-compatible name for older procurement screens and integrations.
Vendor = Supplier


class ProcurementPlan(AuditStampedModel):
    DRAFT = 'draft'
    SUBMITTED = 'submitted'
    REVIEW_APPROVED = 'review_approved'
    REVIEW_REJECTED = 'review_rejected'
    APPROVED = 'approved'
    ED_REJECTED = 'ed_rejected'
    STATUS_CHOICES = (
        (DRAFT, 'Draft'), (SUBMITTED, 'Submitted for Review'),
        (REVIEW_APPROVED, 'Review Approved - Awaiting ED'),
        (REVIEW_REJECTED, 'Returned by Review'),
        (APPROVED, 'Approved'), (ED_REJECTED, 'Rejected by ED'),
    )
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=DRAFT, db_index=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='procurement_plans_reviewed')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='procurement_plans_approved')
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='procurement_plans_rejected')
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    number = models.CharField(max_length=50, unique=True, blank=True)
    requester = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,
                                  related_name='procurements')
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name='procurement_plans')
    donor = models.CharField(max_length=128, blank=True)
    budget = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    fiscal_year = models.CharField(max_length=128)
    budget_period = models.CharField(max_length=20, choices=ProjectBudget.PERIOD_CHOICES, default=ProjectBudget.FULL_YEAR)
    project_budget = models.ForeignKey(ProjectBudget, on_delete=models.PROTECT, null=True, blank=True,
                                       related_name='procurement_plans')
    slug = models.SlugField(null=True, blank=True, unique=True, editable=False)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['number']),
            models.Index(fields=['status']),
            models.Index(fields=['project', 'fiscal_year', 'budget_period']),
        ]

    def __str__(self):
        return self.number

    @property
    def department(self):
        return None

    @property
    def project_head(self):
        return self.project.project_head if self.project else None

    @property
    def project_accountant(self):
        return self.project.project_accountant if self.project else None

    @property
    def project_officer(self):
        return self.project.project_officer if self.project else None

    @property
    def is_locked(self):
        return self.status == self.APPROVED

    @property
    def is_reviewed(self):
        return self.status in {self.REVIEW_APPROVED, self.REVIEW_REJECTED, self.APPROVED, self.ED_REJECTED}

    @property
    def is_approved(self):
        return self.status == self.APPROVED

    @property
    def progress_percentage(self):
        return {
            self.DRAFT: 25, self.SUBMITTED: 50, self.REVIEW_REJECTED: 50,
            self.REVIEW_APPROVED: 75, self.ED_REJECTED: 75, self.APPROVED: 100,
        }.get(self.status, 0)

    @property
    def progress_label(self):
        return self.get_status_display()

    @property
    def remaining_budget(self):
        project_budget = self.resolve_project_budget()
        if project_budget:
            return project_budget.amount_remaining(exclude_plan=self) - self.total_amount
        return self.budget - self.total_amount

    def resolve_project_budget(self):
        if not self.project_id or not self.fiscal_year:
            return None

        exact_budget = ProjectBudget.objects.filter(
            project=self.project,
            fiscal_year=self.fiscal_year,
            period=self.budget_period or ProjectBudget.FULL_YEAR,
        ).first()

        if exact_budget:
            return exact_budget

        if self.budget_period != ProjectBudget.FULL_YEAR:
            return ProjectBudget.objects.filter(
                project=self.project,
                fiscal_year=self.fiscal_year,
                period=ProjectBudget.FULL_YEAR,
            ).first()

        return None

    def amount_already_planned(self):
        project_budget = self.resolve_project_budget()
        if not project_budget:
            return Decimal('0.00')
        return project_budget.procurement_plans.exclude(pk=self.pk).aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')

    def validate_budget_limit(self, proposed_total=None):
        proposed_total = proposed_total if proposed_total is not None else self.total_amount
        project_budget = self.resolve_project_budget()

        if not self.project_id:
            raise ValidationError("A procurement plan must be linked to a project.")

        if not self.fiscal_year:
            raise ValidationError("A procurement plan must include a fiscal year.")

        if not project_budget:
            period = self.get_budget_period_display() if self.budget_period else 'Full Year'
            raise ValidationError(
                f"No budget exists for {self.project} in fiscal year {self.fiscal_year} ({period})."
            )

        used_elsewhere = self.amount_already_planned()
        if used_elsewhere + proposed_total > project_budget.budget_amount:
            remaining = project_budget.budget_amount - used_elsewhere
            raise ValidationError(
                f"Plan total {proposed_total:,.2f} exceeds the remaining budget "
                f"for {self.project} in {self.fiscal_year} ({project_budget.get_period_display()}). "
                f"Remaining budget is {remaining:,.2f}."
            )

        return project_budget

    def update_total(self):
        total = (
            self.items.aggregate(
                total=Sum(
                    F('qty') * F('est_unit_cost'),
                    output_field=DecimalField(
                        max_digits=14,
                        decimal_places=2
                    )
                )
            )['total']
            or Decimal('0.00')
        )

        self.total_amount = total
        self.validate_budget_limit(total)
        self.save(update_fields=['total_amount', 'updated_at'])

    def update_workflow_status(self):
        """
        Programs Head → ED
        """

        if self.rejected_by:
            self.status = self.REVIEW_REJECTED

        elif (
            self.reviewed_by and
            self.approved_by
        ):
            self.status = self.APPROVED

        else:
            self.status = self.SUBMITTED

        self.save(update_fields=['status'])

    def sync_project_fields(self):
        """
        Auto-populate donor and budget from project budget.
        """
        if self.project and not self.donor:
            self.donor = self.project.donor
        project_budget = self.resolve_project_budget()
        if project_budget:
            self.project_budget = project_budget
            self.budget = project_budget.budget_amount

    def save(self, *args, **kwargs):

        if not self.number:
            self.number = f"PP-{self.fiscal_year}-{uuid4().hex[:8].upper()}"
        if not self.slug:
            self.slug = unique_slug(self, self.number or (self.project.name if self.project_id else 'procurement-plan'))

        self.sync_project_fields()

        super().save(*args, **kwargs)


class ProcurementPlanItem(AuditStampedModel):
    procurement = models.ForeignKey(ProcurementPlan, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, help_text='Specification')
    description = models.CharField(max_length=512, help_text='Subject of Procurement')
    qty = models.DecimalField(max_digits=10, decimal_places=2)
    est_unit_cost = models.DecimalField(max_digits=12, decimal_places=2)
    delivery_date = models.DateField(null=True, blank=False)
    unit_measure = models.CharField(max_length=100, default='Pcs', help_text='Unit of measure')

    def line_total(self):
        return (self.qty or 0) * (self.est_unit_cost or 0)

    def clean(self):
        if not self.delivery_date:
            raise ValidationError('A delivery date is required for every procurement item.')

    def __str__(self):
        return f'{self.product.name}'


class Requisition(ApprovalWorkflowModel):
    number = models.CharField(max_length=60, unique=True)
    procurement = models.ForeignKey(ProcurementPlan, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name='requisitions')
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
                                  related_name='issued_requisitions')
    activity_name = models.CharField(max_length=128, blank=True, null=True)
    date = models.DateField(default=timezone.now)
    total = models.DecimalField(max_digits=14, decimal_places=2, default=0.00)
    awarded_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    slug = models.SlugField(null=True, blank=True, unique=True, editable=False)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['number']),
            models.Index(fields=['status']),
            models.Index(fields=['date']),
        ]

    def __str__(self):
        return self.number

    @property
    def project(self):
        return self.procurement.project if self.procurement else None

    @property
    def project_head(self):
        return (
            self.project.project_head
            if self.project else None
        )

    @property
    def project_accountant(self):
        return (
            self.project.project_accountant
            if self.project else None
        )

    @property
    def project_officer(self):
        return (
            self.project.project_officer
            if self.project else None
        )

    @property
    def is_fully_approved(self):
        return (
            self.reviewed_by and
            self.checked_by and
            self.approved_by and
            self.status == 'Approved'
        )

    @property
    def is_locked(self):
        return self.status == 'Approved'

    def update_total(self):
        total = (
            self.items.aggregate(
                total=Sum(
                    F('qty') * F('unit_price'),
                    output_field=DecimalField(
                        max_digits=14,
                        decimal_places=2
                    )
                )
            )['total']
            or Decimal('0.00')
        )

        self.total = total
        self.save(update_fields=['total'])

    def update_workflow_status(self):
        """
        Project Head → Project Accountant → ED
        """

        if self.rejected_by:
            self.status = 'Rejected'

        elif (
            self.reviewed_by and
            self.checked_by and
            self.approved_by
        ):
            self.status = 'Approved'

        else:
            self.status = 'Pending'

        self.save(update_fields=['status'])

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(self, self.number)

        super().save(*args, **kwargs)


class RequisitionItem(models.Model):
    po = models.ForeignKey(Requisition, on_delete=models.CASCADE, related_name='items')
    procurement_item = models.ForeignKey(ProcurementPlanItem, null=True, blank=True, on_delete=models.SET_NULL)
    description = models.CharField(max_length=512, help_text='Subject of Procurement')
    unit_measure = models.CharField(max_length=120, blank=True, null=True)
    qty = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    delivery_date = models.DateField(blank=True, null=True)

    def line_total(self):
        return (self.qty or 0) * (self.unit_price or 0)

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.procurement_item and self.po and self.po.procurement_id:
            if self.procurement_item.procurement_id != self.po.procurement_id:
                raise ValidationError("Selected item is not part of this project's approved procurement plan.")

    def __str__(self):
        return f"{self.description} ({self.qty} @ {self.unit_price})"


class RFQ(AuditStampedModel):
    """Request for Quotation linked to approved Procurement Plans."""
    req = models.ForeignKey(Requisition, on_delete=models.CASCADE, related_name='rfqs', null=True, blank=True)
    reference_no = models.CharField(max_length=60, unique=True)
    date_issued = models.DateField(default=timezone.now)
    status = models.CharField(max_length=30, choices=[('Pending','Pending'),('Sent','Sent'),('Responded','Responded')], default='Pending')
    file = models.FileField(upload_to='Rfq', default='')
    slug = models.SlugField(null=True, blank=True, unique=True, editable=False)
    deadline = models.DateField(null=True, blank=True)
    supplier = models.ManyToManyField(Supplier, related_name='rfq_supplier')

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(self, self.reference_no)
        return super(RFQ, self).save(*args, **kwargs)

    def __str__(self):
        return f"RFQ - {self.reference_no}"


@receiver([post_save, post_delete], sender=RequisitionItem)
def update_req_total(sender, instance, **kwargs):
    po = instance.po
    total = sum(item.line_total() for item in po.items.all())
    po.total = total
    po.save(update_fields=['total'])


class RFQSendLog(models.Model):
    rfq = models.ForeignKey(RFQ, on_delete=models.CASCADE, related_name='send_logs')
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name='rfq_send_logs')
    amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    date_sent = models.DateTimeField(auto_now_add=True)
    awarded_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    request_id = models.CharField(max_length=120, null=True, blank=True)
    responded = models.BooleanField(default=False)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ('rfq', 'supplier')
        ordering = ['-date_sent']

    def __str__(self):
        return f"{self.rfq.reference_no} -> {self.supplier.full_name or self.supplier.title} : {self.amount}"


class PurchaseOrder(models.Model):
    send_log = models.ForeignKey(RFQSendLog, null=True, blank=True, on_delete=models.SET_NULL, related_name='purchase_orders')
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name='purchase_orders')
    rfq = models.ForeignKey(RFQ, null=True, blank=True, on_delete=models.SET_NULL, related_name='purchase_orders')
    requisition = models.ForeignKey(Requisition, on_delete=models.CASCADE,related_name='purchase_orders')
    procurement_plan = models.ForeignKey(ProcurementPlan, on_delete=models.CASCADE, related_name='purchase_orders')
    final_amount = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    po_number = models.CharField(max_length=50, unique=True, null=True)
    issue_date = models.DateField(default=timezone.now)
    due_date = models.DateField(null=True, blank=True)
    remarks = models.TextField(blank=True)
    pdf = models.FileField(upload_to='purchase_orders/', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    sent = models.BooleanField(default=False)
    slug = models.SlugField(null=True, blank=True, unique=True, editable=False)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(self, self.po_number or 'purchase-order')
        return super(PurchaseOrder, self).save(*args, **kwargs)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"PO-{self.po_number} ({self.supplier})"

    def get_absolute_url(self):
        return reverse('procurement:purchase_order_detail', kwargs={'slug': self.slug})


class SupplierSpendReport(models.Model):
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name='spend_reports')
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True, related_name='supplier_spend_reports')
    requisition_item = models.ForeignKey(RequisitionItem, on_delete=models.SET_NULL, null=True, blank=True, related_name='supplier_spend_reports')
    report_year = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    qty = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    awarded_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    line_total = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    grand_total = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_spent = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    purchase_order = models.ForeignKey('PurchaseOrder', on_delete=models.SET_NULL, null=True, blank=True, related_name='spend_reports')
    requisition = models.ForeignKey(Requisition, on_delete=models.SET_NULL, null=True, blank=True, related_name='supplier_spend_reports')
    invoice_no = models.CharField(max_length=80, blank=True)
    invoice_date = models.DateField(null=True, blank=True)
    invoice_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    payment_status = models.CharField(max_length=20, choices=[('Not Paid', 'Not Paid'), ('Paid', 'Paid')], default='Not Paid')
    last_updated = models.DateTimeField(auto_now=True)
    slug = models.SlugField(null=True, blank=True, unique=True, editable=False)

    def save(self, *args, **kwargs):

        if not self.slug:
            self.slug = unique_slug(self, f'{self.supplier_id}-{self.purchase_order_id or "spend"}')

        super().save(*args, **kwargs)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['purchase_order', 'requisition_item'],
                name='unique_supplier_spend_report_per_order_item',
            )
        ]

    def recompute(self):
        if self.purchase_order:
            po = self.purchase_order
            self.supplier = po.supplier
            self.requisition = po.requisition
            self.report_year = po.issue_date.year
            self.awarded_amount = po.final_amount or Decimal('0.00')
            self.grand_total = po.final_amount or Decimal('0.00')
            if self.requisition_item_id:
                item = self.requisition_item
                self.product = item.procurement_item.product if item.procurement_item_id else None
                self.qty = item.qty or Decimal('0.00')
                self.line_total = item.line_total()
            self.total_spent = self.awarded_amount
        self.save(update_fields=[
            'supplier', 'product', 'report_year', 'qty', 'awarded_amount',
            'line_total', 'grand_total', 'total_spent', 'purchase_order',
            'requisition', 'invoice_no',
            'invoice_date', 'invoice_amount', 'payment_status', 'last_updated'
        ])
        return self.total_spent

    @classmethod
    def sync_purchase_order(cls, purchase_order):
        """Rebuild the supplier spend lines for one issued purchase order."""
        if not purchase_order.sent:
            return
        cls.objects.filter(purchase_order=purchase_order).delete()
        items = list(purchase_order.requisition.items.select_related('procurement_item__product'))
        common = {
            'supplier': purchase_order.supplier,
            'purchase_order': purchase_order,
            'requisition': purchase_order.requisition,
            'report_year': purchase_order.issue_date.year,
            'awarded_amount': purchase_order.final_amount or Decimal('0.00'),
            'grand_total': purchase_order.final_amount or Decimal('0.00'),
            'total_spent': purchase_order.final_amount or Decimal('0.00'),
        }
        if not items:
            cls.objects.create(**common)
            return
        cls.objects.bulk_create([
            cls(
                **common,
                product=item.procurement_item.product if item.procurement_item_id else None,
                requisition_item=item,
                qty=item.qty or Decimal('0.00'),
                line_total=item.line_total(),
            )
            for item in items
        ])

    def __str__(self):
        return f"{self.supplier.full_name or self.supplier.title} : {self.total_spent}"
