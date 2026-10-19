import os
import re
from collections import OrderedDict
from io import BytesIO

from django.conf import settings
from django.contrib import messages
from django.core.files.base import ContentFile
from django.core.mail import EmailMessage
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from xhtml2pdf import pisa

from .forms import DirectPurchaseForm, PurchaseOrderForm
from .models import PurchaseOrder, RFQSendLog, SupplierSpendReport, Supplier
from .models import Requisition
from .thresholds import DIRECT_PURCHASE_LIMIT, uses_direct_purchase
from .views_rfq import procurement_required


def _po_pdf(po):
    html = render_to_string('procurement/purchase_order_pdf.html', {
        'po': po,
        'requisition': po.requisition,
        'items': po.requisition.items.all(),
        'logo_path': os.path.join(settings.BASE_DIR, 'static', 'img', 'dds_nk.jpg'),
        'generated_at': timezone.now(),
    })
    output = BytesIO()
    result = pisa.CreatePDF(BytesIO(html.encode('utf-8')), dest=output)
    if result.err:
        raise ValueError('The purchase order PDF could not be generated.')
    return output.getvalue()


@procurement_required
def create_direct_purchase(request, requisition_slug):
    requisition = get_object_or_404(
        Requisition.objects.select_related('procurement__project').prefetch_related('items'),
        slug=requisition_slug,
        status='Approved',
    )
    if not uses_direct_purchase(requisition.total):
        messages.info(request, 'This requisition is above the UGX 200,000 direct-purchase threshold and must use an RFQ.')
        return redirect('procurement:rfq_create', requisition.slug)

    existing_po = PurchaseOrder.objects.filter(requisition=requisition, sent=True).select_related('supplier').first()
    if existing_po:
        messages.info(request, f'This requisition already has Purchase Order {existing_po.po_number}.')
        return redirect('procurement:purchase_order_detail', slug=existing_po.slug)

    if request.method == 'POST':
        form = DirectPurchaseForm(request.POST, requisition=requisition)
        if form.is_valid():
            with transaction.atomic():
                po = PurchaseOrder(
                    supplier=form.cleaned_data['supplier'],
                    requisition=requisition,
                    procurement_plan=requisition.procurement,
                    final_amount=form.cleaned_data['final_amount'],
                    due_date=form.cleaned_data['due_date'],
                    remarks=form.cleaned_data['remarks'],
                    po_number=f'DP-{timezone.now():%Y}-{requisition.pk:05d}',
                    sent=True,
                )
                po.save()
                pdf_content = _po_pdf(po)
                safe_number = re.sub(r'[^A-Za-z0-9_-]+', '-', po.po_number).strip('-')
                po.pdf.save(f'{safe_number}.pdf', ContentFile(pdf_content), save=True)
                SupplierSpendReport.sync_purchase_order(po)
            if po.supplier.email:
                try:
                    email = EmailMessage(
                        subject=f'Direct Purchase Order {po.po_number}',
                        body=f'Dear {po.supplier.contact_person or po.supplier.name},\n\nPlease find attached Purchase Order {po.po_number}.\n\nRegards,\nDDS-NK Procurement Team',
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        to=[po.supplier.email],
                    )
                    email.attach(f'{po.po_number}.pdf', pdf_content, 'application/pdf')
                    email.send()
                except Exception:
                    messages.warning(request, 'The direct purchase order was created, but the supplier email could not be sent.')
            messages.success(request, f'Direct Purchase Order {po.po_number} was created successfully.')
            return redirect('procurement:purchase_order_detail', slug=po.slug)
    else:
        form = DirectPurchaseForm(
            requisition=requisition,
            initial={'final_amount': requisition.total},
        )
    return render(request, 'procurement/direct_purchase_form.html', {
        'form': form,
        'requisition': requisition,
        'items': requisition.items.all(),
        'threshold': DIRECT_PURCHASE_LIMIT,
    })


@procurement_required
def create_purchase_order(request, send_log_id):
    send_log = get_object_or_404(
        RFQSendLog.objects.select_related('rfq__req__procurement', 'supplier').prefetch_related('rfq__req__items'),
        pk=send_log_id,
    )
    rfq = send_log.rfq
    requisition = rfq.req
    existing_po = PurchaseOrder.objects.filter(rfq=rfq, sent=True).select_related('supplier').first()
    if existing_po:
        messages.info(request, f'This RFQ has already been awarded to {existing_po.supplier}.')
        return redirect('procurement:purchase_order_detail', slug=existing_po.slug)
    if rfq.status not in {'Sent', 'Responded'}:
        messages.warning(request, 'The RFQ must be sent before a supplier can be awarded.')
        return redirect('procurement:rfq_detail', slug=rfq.slug)

    if request.method == 'POST':
        if not send_log.responded:
            messages.warning(request, 'Mark this supplier as responded before awarding a purchase order.')
            return redirect('procurement:rfq_detail', slug=rfq.slug)
        form = PurchaseOrderForm(request.POST, supplier=send_log.supplier)
        if form.is_valid():
            with transaction.atomic():
                po = form.save(commit=False)
                po.send_log = send_log
                po.supplier = send_log.supplier
                po.rfq = rfq
                po.requisition = requisition
                po.procurement_plan = requisition.procurement
                po.po_number = f'PO-{timezone.now():%Y}-{rfq.pk:05d}-{send_log.supplier.pk:04d}'
                po.sent = True
                po.save()
                send_log.awarded_amount = po.final_amount
                send_log.save(update_fields=['awarded_amount'])
                pdf_content = _po_pdf(po)
                safe_number = re.sub(r'[^A-Za-z0-9_-]+', '-', po.po_number).strip('-')
                po.pdf.save(f'{safe_number}.pdf', ContentFile(pdf_content), save=True)
                SupplierSpendReport.sync_purchase_order(po)
            if po.supplier.email:
                try:
                    email = EmailMessage(
                        subject=f'Purchase Order {po.po_number}',
                        body=f'Dear {po.supplier.contact_person or po.supplier.name},\n\nPlease find attached Purchase Order {po.po_number}.\n\nRegards,\nDDS-NK Procurement Team',
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        to=[po.supplier.email],
                    )
                    email.attach(f'{po.po_number}.pdf', pdf_content, 'application/pdf')
                    email.send()
                except Exception:
                    messages.warning(request, 'The purchase order was created, but the supplier email could not be sent.')
            messages.success(request, f'Purchase Order {po.po_number} was created and awarded to {po.supplier}.')
            return redirect('procurement:purchase_order_detail', slug=po.slug)
    else:
        form = PurchaseOrderForm(supplier=send_log.supplier, initial={'final_amount': send_log.amount})
    return render(request, 'procurement/purchase_order_form.html', {
        'form': form, 'send_log': send_log, 'rfq': rfq,
        'requisition': requisition, 'items': requisition.items.all(),
    })


@procurement_required
def purchase_order_list(request):
    orders = PurchaseOrder.objects.filter(sent=True).select_related('supplier', 'requisition', 'rfq').order_by('-created_at')
    return render(request, 'procurement/purchase_order_list.html', {
        'orders': orders,
        'total_orders': orders.count(),
        'total_amount': sum((order.final_amount or 0) for order in orders),
    })


@procurement_required
def purchase_order_detail(request, slug):
    po = get_object_or_404(PurchaseOrder.objects.select_related('supplier', 'rfq', 'requisition', 'procurement_plan').prefetch_related('requisition__items'), slug=slug)
    return render(request, 'procurement/purchase_order_detail.html', {'po': po, 'items': po.requisition.items.all()})


@procurement_required
def supplier_spend_report(request):
    """Show issued PO spend by year and supplier, down to requisition item."""
    years = sorted(
        set(PurchaseOrder.objects.filter(sent=True).values_list('issue_date__year', flat=True)),
        reverse=True,
    )
    selected_year = request.GET.get('year')
    try:
        selected_year = int(selected_year) if selected_year else (years[0] if years else timezone.now().year)
    except (TypeError, ValueError):
        selected_year = years[0] if years else timezone.now().year

    selected_supplier = request.GET.get('supplier', '')
    reports = SupplierSpendReport.objects.filter(
        report_year=selected_year,
        purchase_order__sent=True,
    ).select_related('supplier', 'product', 'purchase_order', 'requisition_item')
    if selected_supplier:
        reports = reports.filter(supplier_id=selected_supplier)

    grouped = OrderedDict()
    awarded_by_po = {}
    for report in reports.order_by('supplier__name', 'purchase_order__issue_date', 'purchase_order_id', 'id'):
        bucket = grouped.setdefault(report.supplier_id, {
            'supplier': report.supplier,
            'rows': [],
            'grand_total': 0,
        })
        bucket['rows'].append(report)
        if report.purchase_order_id not in awarded_by_po:
            awarded_by_po[report.purchase_order_id] = report.awarded_amount or 0
            bucket['grand_total'] += report.awarded_amount or 0

    supplier_rows = list(grouped.values())
    organization_total = sum(
        (amount or 0)
        for amount in PurchaseOrder.objects.filter(
            sent=True, issue_date__year=selected_year
        ).values_list('final_amount', flat=True)
    )
    suppliers = Supplier.objects.filter(active=True).order_by('name')
    return render(request, 'procurement/supplier_spend_report.html', {
        'supplier_rows': supplier_rows,
        'organization_total': organization_total,
        'years': years,
        'selected_year': selected_year,
        'selected_supplier': str(selected_supplier),
        'suppliers': suppliers,
    })
