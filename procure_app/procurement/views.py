from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.conf import settings
from django.http import HttpResponse
from django.template.loader import render_to_string
from io import BytesIO
import os
import re
from xhtml2pdf import pisa

from core.access import (
    access_required,
    ensure_separation_of_duty,
    is_executive_director,
    signature_required,
    user_has_access,
)
from core.utils import audit, recent_audit_activity, stamp_audit
from notifications.services import notify_group, notify_user, notify_users
from .forms import (
    ProductForm,
    ProcurementPlanForm,
    ProcurementPlanItemFormSet,
    SupplierForm,
)
from .models import Product, ProcurementPlan, Supplier
from .project_models import Project, ProjectBudget

import calendar
from decimal import Decimal

from django.db.models import Count, Sum
from django.db.models.functions import TruncMonth
from django.shortcuts import render
from django.utils import timezone

from .models import (
    ProcurementPlan,
    Supplier,
    Product,
    Requisition,
    RFQ,
    PurchaseOrder,
)
from .project_models import Project


User = get_user_model()


def allowed(request):
    return user_has_access(request.user, 'procurement')


def can_review(request):
    return request.user.groups.filter(name__iexact='REVIEW').exists()


def can_decide_as_ed(request):
    return is_executive_director(request.user)


def _plan_url(plan):
    return reverse('procurement:plan_detail', kwargs={'slug': plan.slug})


def _notify_ed(plan):
    users = User.objects.filter(
        Q(is_superuser=True) | Q(groups__name__in=['ED', 'Executive Director']),
        is_active=True,
    ).distinct()
    notify_users(
        users,
        'Procurement plan awaiting ED decision',
        f'{plan.number} for {plan.project.name} was approved by REVIEW and is awaiting your decision.',
        level='warning', url=_plan_url(plan), email=True,
    )


def _notify_requester(plan, title, message, level='info'):
    notify_user(plan.requester, title, message, level=level, url=_plan_url(plan), email=True)


def _item_total(formset):
    return sum((form.cleaned_data.get('qty') or 0) * (form.cleaned_data.get('est_unit_cost') or 0)
               for form in formset.forms if form.cleaned_data and not form.cleaned_data.get('DELETE'))


def _validation_message(error, fallback='Please correct the highlighted errors.'):
    """Return one clean message instead of ValidationError's list repr."""
    return error.messages[0] if getattr(error, 'messages', None) else fallback


# @access_required('procurement')
# def dashboard(request):
#     plans = ProcurementPlan.objects.select_related('project', 'requester')
#     return render(request, 'procurement/dashboard.html', {
#         'requests': plans.count(),
#         'submitted': plans.filter(status=ProcurementPlan.SUBMITTED).count(),
#         'approved': plans.filter(status=ProcurementPlan.APPROVED).count(),
#         'vendors': Supplier.objects.filter(active=True).count(),
#         'products': Product.objects.filter(active=True).count(),
#         'projects': _project_count(),
#         'recent': plans[:8],
#     })

@access_required('procurement')
def dashboard(request):
    today = timezone.localdate()
    current_year = today.year

    plans = ProcurementPlan.objects.select_related(
        'project',
        'requester',
    ).order_by('-created_at')

    # Procurement plan workflow
    plan_status_counts = {
        row['status']: row['total']
        for row in ProcurementPlan.objects.values('status').annotate(
            total=Count('pk')
        )
    }

    total_plans = plans.count()
    draft_plans = plan_status_counts.get(ProcurementPlan.DRAFT, 0)
    submitted_plans = plan_status_counts.get(ProcurementPlan.SUBMITTED, 0)
    review_approved = plan_status_counts.get(
        ProcurementPlan.REVIEW_APPROVED, 0
    )
    review_rejected = plan_status_counts.get(
        ProcurementPlan.REVIEW_REJECTED, 0
    )
    approved_plans = plan_status_counts.get(ProcurementPlan.APPROVED, 0)
    ed_rejected = plan_status_counts.get(ProcurementPlan.ED_REJECTED, 0)

    pending_review = submitted_plans
    awaiting_ed = review_approved
    rejected_plans = review_rejected + ed_rejected

    plan_financials = plans.aggregate(
        total_budget=Sum('budget'),
        total_planned=Sum('total_amount'),
    )

    total_budget = plan_financials['total_budget'] or Decimal('0.00')
    total_planned = plan_financials['total_planned'] or Decimal('0.00')
    remaining_plan_budget = total_budget - total_planned

    # Supplier and catalogue overview
    total_suppliers = Supplier.objects.count()
    active_suppliers = Supplier.objects.filter(active=True).count()
    prequalified_suppliers = Supplier.objects.filter(
        prequalified=True
    ).count()
    inactive_suppliers = Supplier.objects.filter(active=False).count()
    active_products = Product.objects.filter(active=True).count()
    total_products = Product.objects.count()
    total_projects = Project.objects.count()

    # Requisitions
    total_requisitions = Requisition.objects.count()
    pending_requisitions = Requisition.objects.filter(
        status='Pending'
    ).count()
    approved_requisitions = Requisition.objects.filter(
        status='Approved'
    ).count()
    rejected_requisitions = Requisition.objects.filter(
        status='Rejected'
    ).count()

    requisition_financials = Requisition.objects.aggregate(
        total_value=Sum('total'),
        awarded_value=Sum('awarded_amount'),
    )

    requisition_value = (
        requisition_financials['total_value'] or Decimal('0.00')
    )
    awarded_value = (
        requisition_financials['awarded_value'] or Decimal('0.00')
    )

    # Requests for quotation
    total_rfqs = RFQ.objects.count()
    pending_rfqs = RFQ.objects.filter(status='Pending').count()
    sent_rfqs = RFQ.objects.filter(status='Sent').count()
    responded_rfqs = RFQ.objects.filter(status='Responded').count()

    # Purchase orders
    total_purchase_orders = PurchaseOrder.objects.count()
    sent_purchase_orders = PurchaseOrder.objects.filter(
        sent=True
    ).count()

    po_financials = PurchaseOrder.objects.filter(sent=True).aggregate(
        committed_value=Sum('final_amount'),
    )
    committed_value = (
        po_financials['committed_value'] or Decimal('0.00')
    )

    # Monthly purchase order commitments for the current calendar year.
    monthly_rows = (
        PurchaseOrder.objects.filter(
            sent=True,
            issue_date__year=current_year,
        )
        .annotate(month=TruncMonth('issue_date'))
        .values('month')
        .annotate(total=Sum('final_amount'))
        .order_by('month')
    )

    monthly_lookup = {
        row['month'].month: row['total'] or Decimal('0.00')
        for row in monthly_rows
        if row['month']
    }

    monthly_labels = [
        calendar.month_abbr[month]
        for month in range(1, 13)
    ]
    monthly_values = [
        float(monthly_lookup.get(month, Decimal('0.00')))
        for month in range(1, 13)
    ]

    # Plan workflow chart
    plan_chart_labels = [
        'Draft',
        'Submitted',
        'Review approved',
        'Review rejected',
        'Approved',
        'ED rejected',
    ]
    plan_chart_values = [
        draft_plans,
        submitted_plans,
        review_approved,
        review_rejected,
        approved_plans,
        ed_rejected,
    ]

    # Recent plans
    recent_plans = plans[:8]

    # Recent audit activity
    recent_activity = recent_audit_activity(request.user)

    chart_data = {
        'planStatusLabels': plan_chart_labels,
        'planStatusValues': plan_chart_values,
        'monthlyLabels': monthly_labels,
        'monthlyValues': monthly_values,
        'supplierLabels': ['Active', 'Inactive'],
        'supplierValues': [active_suppliers, inactive_suppliers],
    }

    context = {
        # Preserve existing dashboard context keys.
        'requests': total_plans,
        'submitted': submitted_plans,
        'approved': approved_plans,
        'vendors': active_suppliers,
        'products': active_products,
        'projects': total_projects,
        'recent': recent_plans,

        # Executive KPIs
        'total_plans': total_plans,
        'draft_plans': draft_plans,
        'pending_review': pending_review,
        'awaiting_ed': awaiting_ed,
        'rejected_plans': rejected_plans,
        'total_budget': total_budget,
        'total_planned': total_planned,
        'remaining_plan_budget': remaining_plan_budget,

        # Supplier and catalogue metrics
        'total_suppliers': total_suppliers,
        'active_suppliers': active_suppliers,
        'prequalified_suppliers': prequalified_suppliers,
        'total_products': total_products,

        # Requisitions and RFQs
        'total_requisitions': total_requisitions,
        'pending_requisitions': pending_requisitions,
        'approved_requisitions': approved_requisitions,
        'rejected_requisitions': rejected_requisitions,
        'requisition_value': requisition_value,
        'awarded_value': awarded_value,
        'total_rfqs': total_rfqs,
        'pending_rfqs': pending_rfqs,
        'sent_rfqs': sent_rfqs,
        'responded_rfqs': responded_rfqs,

        # Purchase orders
        'total_purchase_orders': total_purchase_orders,
        'sent_purchase_orders': sent_purchase_orders,
        'committed_value': committed_value,

        # Supporting content
        'recent_activity': recent_activity,
        'chart_data': chart_data,
        'current_year': current_year,
        'today': today,
    }

    return render(
        request,
        'procurement/dashboard.html',
        context,
    )



def _project_count():
    from .project_models import Project
    return Project.objects.count()


@access_required('procurement')
def plan_list(request):
    query = request.GET.get('q', '').strip()
    plans = ProcurementPlan.objects.select_related('project', 'requester').prefetch_related('items')
    if query:
        plans = plans.filter(
            Q(number__icontains=query) | Q(project__name__icontains=query) |
            Q(project__code__icontains=query) | Q(fiscal_year__icontains=query)
        )
    return render(request, 'procurement/plan_list.html', {'plans': plans, 'query': query})


@access_required('procurement')
def plan_detail(request, slug):
    plan = get_object_or_404(
        ProcurementPlan.objects.select_related('project', 'requester', 'reviewed_by', 'approved_by', 'rejected_by').prefetch_related('items__product'),
        slug=slug,
    )
    return render(request, 'procurement/plan_detail.html', {
        'plan': plan,
        'can_review': can_review(request) and plan.status == ProcurementPlan.SUBMITTED,
        'can_decide_as_ed': can_decide_as_ed(request) and plan.status == ProcurementPlan.REVIEW_APPROVED,
        'can_edit': plan.requester_id == request.user.id and plan.status != ProcurementPlan.APPROVED,
        'can_delete': plan.requester_id == request.user.id and plan.status != ProcurementPlan.APPROVED,
    })


@access_required('procurement')
def plan_pdf_export(request, slug):
    """Download the official PDF record for an ED-approved plan only."""
    plan = get_object_or_404(
        ProcurementPlan.objects.select_related(
            'project', 'project__project_head', 'requester',
            'reviewed_by', 'approved_by', 'project_budget',
        ).prefetch_related('items__product'),
        slug=slug,
    )
    if not plan.is_approved:
        messages.warning(request, 'The official PDF is available after ED approval.')
        return redirect('procurement:plan_detail', slug=plan.slug)

    logo_path = os.path.join(settings.BASE_DIR, 'static', 'img', 'dds_nk.jpg')
    html = render_to_string('procurement/plan_pdf.html', {
        'plan': plan,
        'logo_path': logo_path,
        'requester_signature': _signature_path(plan.requester),
        'reviewer_signature': _signature_path(plan.reviewed_by),
        'approver_signature': _signature_path(plan.approved_by),
        'generated_at': timezone.now(),
    })
    output = BytesIO()
    result = pisa.CreatePDF(BytesIO(html.encode('utf-8')), dest=output)
    if result.err:
        messages.error(request, 'The approved plan PDF could not be generated. Please try again.')
        return redirect('procurement:plan_detail', slug=plan.slug)

    safe_number = re.sub(r'[^A-Za-z0-9_-]+', '-', plan.number).strip('-') or 'plan'
    response = HttpResponse(output.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="DDS-NK_Procurement_Plan_{safe_number}.pdf"'
    return response


def _signature_path(user):
    """Return a filesystem path usable by the PDF renderer, if uploaded."""
    try:
        return user.signature.path if user and user.signature else ''
    except (AttributeError, ValueError):
        return ''


@signature_required
def plan_create(request):
    if not (user_has_access(request.user, 'procurement') or Project.objects.filter(project_head=request.user).exists() or is_executive_director(request.user)):
        return redirect('portal')
    form = ProcurementPlanForm(request.POST or None, user=request.user)
    formset = ProcurementPlanItemFormSet(request.POST or None, prefix='items')
    if request.method == 'POST' and form.is_valid() and formset.is_valid():
        proposed_total = _item_total(formset)
        if proposed_total > (form.cleaned_data.get('budget') or 0):
            form.add_error('budget', 'The item total cannot exceed the selected project budget.')
        else:
            plan = stamp_audit(form.save(commit=False), request.user, creating=True)
            plan.requester = request.user
            plan.status = ProcurementPlan.SUBMITTED
            try:
                plan.validate_budget_limit(proposed_total)
                with transaction.atomic():
                    plan.save()
                    formset.instance = plan
                    _save_items(formset, request.user)
                    plan.update_total()
            except ValidationError as exc:
                form.add_error(None, _validation_message(exc))
            else:
                notify_group(
                    'REVIEW', 'Procurement plan awaiting review',
                    f'{plan.number} for {plan.project.name} was submitted by {request.user.get_full_name() or request.user.username}.',
                    level='warning', url=_plan_url(plan), email=True,
                )
                audit(request, 'Submitted procurement plan', 'Procurement', plan)
                messages.success(request, 'Procurement plan submitted to REVIEW.')
                return redirect('procurement:plan_detail', slug=plan.slug)
    return render(request, 'procurement/plan_form.html', {'form': form, 'formset': formset, 'title': 'Create Procurement Plan', 'plan': None})


@signature_required
def plan_update(request, slug):
    if not (user_has_access(request.user, 'procurement') or Project.objects.filter(project_head=request.user).exists() or is_executive_director(request.user)):
        return redirect('portal')
    plan = get_object_or_404(ProcurementPlan, slug=slug)
    if plan.requester_id != request.user.id or plan.status == ProcurementPlan.APPROVED:
        messages.warning(request, 'Only the requesting Project Head can revise this plan at its current stage.')
        return redirect('procurement:plan_detail', slug=plan.slug)
    form = ProcurementPlanForm(request.POST or None, instance=plan, user=request.user)
    formset = ProcurementPlanItemFormSet(request.POST or None, instance=plan, prefix='items')
    if request.method == 'POST' and form.is_valid() and formset.is_valid():
        proposed_total = _item_total(formset)
        if proposed_total > (form.cleaned_data.get('budget') or 0):
            form.add_error('budget', 'The item total cannot exceed the selected project budget.')
        else:
            plan = stamp_audit(form.save(commit=False), request.user)
            plan.status = ProcurementPlan.SUBMITTED
            plan.reviewed_by = plan.approved_by = plan.rejected_by = None
            plan.reviewed_at = plan.approved_at = plan.rejected_at = None
            plan.rejection_reason = ''
            try:
                plan.validate_budget_limit(proposed_total)
                with transaction.atomic():
                    plan.save()
                    _save_items(formset, request.user)
                    plan.update_total()
            except ValidationError as exc:
                form.add_error(None, _validation_message(exc))
            else:
                notify_group('REVIEW', 'Revised procurement plan awaiting review', f'{plan.number} was revised and resubmitted.', level='warning', url=_plan_url(plan), email=True)
                messages.success(request, 'Revised procurement plan submitted to REVIEW.')
                return redirect('procurement:plan_detail', slug=plan.slug)
    if request.method == 'POST':
        messages.error(request, 'The procurement plan was not saved. Please correct the highlighted errors and try again.')
    return render(request, 'procurement/plan_form.html', {'form': form, 'formset': formset, 'title': 'Revise Procurement Plan', 'plan': plan})


@login_required
def plan_delete(request, slug):
    plan = get_object_or_404(ProcurementPlan, slug=slug)
    if plan.requester_id != request.user.id or plan.status == ProcurementPlan.APPROVED:
        messages.warning(request, 'Approved plans cannot be deleted, and only the requester can delete this plan.')
        return redirect('procurement:plan_detail', slug=plan.slug)
    if request.method == 'POST':
        number = plan.number
        plan.delete()
        messages.success(request, f'Procurement plan {number} was deleted.')
        return redirect('procurement:plans')
    return render(request, 'procurement/delete_confirmation.html', {
        'object': plan,
        'cancel_url': 'procurement:plan_detail',
        'cancel_slug': plan.slug,
        'title': 'Delete procurement plan',
    })


def _save_items(formset, user):
    items = formset.save(commit=False)
    for item in items:
        stamp_audit(item, user, creating=item._state.adding)
        item.save()
    for item in formset.deleted_objects:
        item.delete()


@access_required('procurement')
@signature_required
def plan_decision(request, slug):
    plan = get_object_or_404(ProcurementPlan, slug=slug)
    if request.method != 'POST':
        return redirect('procurement:plan_detail', slug=plan.slug)
    decision = request.POST.get('decision')
    comment = request.POST.get('comment', '').strip()
    now = timezone.now()

    if plan.status == ProcurementPlan.SUBMITTED and can_review(request):
        try:
            ensure_separation_of_duty(plan, request.user, fields=('created_by', 'reviewed_by', 'approved_by'))
        except ValidationError as exc:
            messages.error(request, exc.messages[0] if exc.messages else 'This document cannot be signed by the current user.')
            return redirect('procurement:plan_detail', slug=plan.slug)
        if decision == 'approve':
            plan.status = ProcurementPlan.REVIEW_APPROVED
            plan.reviewed_by, plan.reviewed_at = request.user, now
            plan.save()
            _notify_ed(plan)
            messages.success(request, 'Plan approved by REVIEW and sent to the ED.')
        elif decision in {'reject', 'deny'}:
            plan.status = ProcurementPlan.REVIEW_REJECTED
            plan.reviewed_by, plan.reviewed_at = request.user, now
            plan.rejected_by, plan.rejection_reason = request.user, comment or 'Returned by REVIEW.'
            plan.save()
            _notify_requester(plan, 'Procurement plan returned by REVIEW', f'{plan.number} was returned for revision. Reason: {plan.rejection_reason}', 'error')
            messages.warning(request, 'The requester has been notified of the REVIEW decision.')
        else:
            messages.error(request, 'Select a valid REVIEW decision.')
    elif plan.status == ProcurementPlan.REVIEW_APPROVED and can_decide_as_ed(request):
        try:
            ensure_separation_of_duty(plan, request.user, fields=('created_by', 'reviewed_by', 'approved_by'))
        except ValidationError as exc:
            messages.error(request, exc.messages[0] if exc.messages else 'This document cannot be signed by the current user.')
            return redirect('procurement:plan_detail', slug=plan.slug)
        if decision == 'approve':
            plan.status = ProcurementPlan.APPROVED
            plan.approved_by, plan.approved_at = request.user, now
            plan.save()
            _notify_requester(plan, 'Procurement plan approved', f'{plan.number} was approved by the Executive Director.', 'success')
            messages.success(request, 'Procurement plan approved.')
        elif decision in {'reject', 'deny'}:
            plan.status = ProcurementPlan.ED_REJECTED
            plan.rejected_by, plan.rejection_reason = request.user, comment or 'Rejected by the Executive Director.'
            plan.save()
            _notify_requester(plan, 'Procurement plan rejected by ED', f'{plan.number} was rejected by the Executive Director. Reason: {plan.rejection_reason}', 'error')
            messages.warning(request, 'The requester has been notified of the ED decision.')
        else:
            messages.error(request, 'Select a valid ED decision.')
    else:
        messages.error(request, 'You are not authorized to act on this plan at its current stage.')
    return redirect('procurement:plan_detail', slug=plan.slug)


@login_required
def project_budget_info(request, slug):
    project = get_object_or_404(Project, slug=slug)
    fiscal_year = request.GET.get('fiscal_year') or ProjectBudget.current_fiscal_year()
    period = request.GET.get('period') or ProjectBudget.FULL_YEAR
    budget = ProjectBudget.objects.filter(project=project, fiscal_year=fiscal_year, period=period).first()
    if not budget and period != ProjectBudget.FULL_YEAR:
        budget = ProjectBudget.objects.filter(project=project, fiscal_year=fiscal_year, period=ProjectBudget.FULL_YEAR).first()
    return JsonResponse({'donor': project.donor or '', 'budget': str(budget.budget_amount) if budget else '', 'budget_period': budget.period if budget else ''})


@login_required
def product_info(request, code):
    product = get_object_or_404(Product, code=code)
    return JsonResponse({'name': product.name, 'unit_price': str(product.est_unit_cost), 'unit': product.get_unit_display()})


# Compatibility alias for the previous requests route.
requests = plan_list


@access_required('procurement')
def supplier_list(request):
    query = request.GET.get('q', '').strip()
    items = Supplier.objects.all()
    if query:
        items = items.filter(Q(name__icontains=query) | Q(supplier_code__icontains=query) | Q(category__icontains=query))
    return render(request, 'procurement/supplier_list.html', {'items': items, 'query': query})


@access_required('procurement', manage=True)
def supplier_create(request):
    return _supplier_form(request)


@access_required('procurement', manage=True)
def supplier_update(request, slug):
    return _supplier_form(request, get_object_or_404(Supplier, slug=slug))


@access_required('procurement', manage=True)
def supplier_delete(request, slug):
    supplier = get_object_or_404(Supplier, slug=slug)
    if request.method == 'POST':
        supplier.delete()
        messages.success(request, 'Supplier deleted.')
        return redirect('procurement:suppliers')
    return render(request, 'procurement/delete_confirmation.html', {'object': supplier, 'cancel_url': 'procurement:suppliers', 'title': 'Delete supplier'})


def _supplier_form(request, instance=None):
    form = SupplierForm(request.POST or None, request.FILES or None, instance=instance)
    if form.is_valid():
        obj = stamp_audit(form.save(commit=False), request.user, creating=instance is None)
        obj.save()
        messages.success(request, f"Supplier {'updated' if instance else 'created'} successfully.")
        return redirect('procurement:suppliers')
    return render(request, 'procurement/entity_form.html', {'form': form, 'title': 'Edit Supplier' if instance else 'New Supplier', 'entity': 'Supplier', 'cancel_url': 'procurement:suppliers'})


@access_required('procurement')
def product_list(request):
    query = request.GET.get('q', '').strip()
    items = Product.objects.select_related('supplier')
    if query:
        items = items.filter(Q(name__icontains=query) | Q(code__icontains=query) | Q(category__icontains=query))
    return render(request, 'procurement/product_list.html', {'items': items, 'query': query})


@access_required('procurement', manage=True)
def product_create(request):
    return _product_form(request)


@access_required('procurement', manage=True)
def product_update(request, code):
    return _product_form(request, get_object_or_404(Product, code=code))


@access_required('procurement', manage=True)
def product_delete(request, code):
    product = get_object_or_404(Product, code=code)
    if request.method == 'POST':
        product.delete()
        messages.success(request, 'Product deleted.')
        return redirect('procurement:products')
    return render(request, 'procurement/delete_confirmation.html', {'object': product, 'cancel_url': 'procurement:products', 'title': 'Delete product'})


def _product_form(request, instance=None):
    form = ProductForm(request.POST or None, instance=instance)
    if form.is_valid():
        form.save()
        messages.success(request, f"Product {'updated' if instance else 'created'} successfully.")
        return redirect('procurement:products')
    return render(request, 'procurement/entity_form.html', {'form': form, 'title': 'Edit Product' if instance else 'New Product', 'entity': 'Product', 'cancel_url': 'procurement:products'})
