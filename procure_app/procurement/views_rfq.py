import os
import re
from functools import wraps
from io import BytesIO

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.core.mail import EmailMessage, get_connection
from django.db import transaction
from django.db.models import Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from xhtml2pdf import pisa

from notifications.services import notify_users

from .forms import RFQForm
from .models import RFQ, RFQSendLog, Requisition
from .thresholds import uses_direct_purchase


def is_procurement_member(user):
    return bool(user.is_authenticated and (
        user.is_superuser or user.groups.filter(name__iexact='Procurement').exists()
    ))


def procurement_required(view):
    @wraps(view)
    @login_required
    def wrapped(request, *args, **kwargs):
        if not is_procurement_member(request.user):
            messages.error(request, 'Only members of the Procurement group can manage RFQs.')
            return redirect('procurement:req_list')
        return view(request, *args, **kwargs)
    return wrapped


def _rfq_url(rfq):
    return reverse('procurement:rfq_detail', kwargs={'slug': rfq.slug})


def _reference_for(requisition):
    project_code = requisition.project.code if requisition.project else 'PROJECT'
    project_code = re.sub(r'[^A-Za-z0-9]+', '-', project_code).strip('-').upper()
    return f'RFQ-{project_code}-{timezone.now().year}-{requisition.pk:05d}'


def _rfq_pdf(rfq):
    requisition = rfq.req
    html = render_to_string('procurement/rfq_pdf.html', {
        'rfq': rfq,
        'requisition': requisition,
        'plan': requisition.procurement,
        'items': requisition.items.select_related('procurement_item__product').all(),
        'suppliers': rfq.supplier.all(),
        'logo_path': os.path.join(settings.BASE_DIR, 'static', 'img', 'dds_nk.jpg'),
        'generated_at': timezone.now(),
    })
    output = BytesIO()
    result = pisa.CreatePDF(BytesIO(html.encode('utf-8')), dest=output)
    if result.err:
        raise ValueError('The RFQ PDF could not be generated.')
    return output.getvalue()


@procurement_required
def create_rfq(request, requisition_slug):
    requisition = get_object_or_404(
        Requisition.objects.select_related('procurement__project'),
        slug=requisition_slug, status='Approved',
    )
    if uses_direct_purchase(requisition.total):
        messages.info(request, 'Requisitions up to UGX 200,000 use the direct-purchase route and do not require an RFQ.')
        return redirect('procurement:direct_purchase_create', requisition.slug)
    existing = requisition.rfqs.order_by('-created_at').first()
    if existing:
        messages.info(request, f'RFQ {existing.reference_no} already exists for this requisition.')
        return redirect('procurement:rfq_detail', slug=existing.slug)
    if request.method == 'POST':
        form = RFQForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                rfq = form.save(commit=False)
                rfq.req = requisition
                rfq.reference_no = _reference_for(requisition)
                rfq.date_issued = timezone.now().date()
                rfq.status = 'Pending'
                rfq.created_by = request.user
                rfq.save()
                form.save_m2m()
                try:
                    pdf_content = _rfq_pdf(rfq)
                    safe_ref = re.sub(r'[^A-Za-z0-9_-]+', '-', rfq.reference_no).strip('-')
                    rfq.file.save(f'{safe_ref}.pdf', ContentFile(pdf_content), save=True)
                except ValueError as error:
                    messages.error(request, str(error))
                    return redirect('procurement:rfq_list')
            messages.success(request, f'{rfq.reference_no} generated for requisition {requisition.number}.')
            return redirect('procurement:rfq_detail', slug=rfq.slug)
    else:
        form = RFQForm()
    return render(request, 'procurement/rfq_form.html', {
        'form': form, 'requisition': requisition,
        'items': requisition.items.select_related('procurement_item__product').all(),
    })


@procurement_required
def rfq_list(request):
    rfqs = RFQ.objects.select_related('req__procurement__project', 'created_by').prefetch_related('supplier').order_by('-created_at')
    search = request.GET.get('search', '').strip()
    status = request.GET.get('status', '').strip()
    if search:
        rfqs = rfqs.filter(Q(reference_no__icontains=search) | Q(req__number__icontains=search) | Q(req__procurement__project__name__icontains=search))
    if status:
        rfqs = rfqs.filter(status=status)
    return render(request, 'procurement/rfq_list.html', {
        'rfqs': rfqs, 'search': search, 'status_filter': status,
        'total_rfqs': rfqs.count(), 'sent_count': rfqs.filter(status='Sent').count(),
        'responded_count': rfqs.filter(status='Responded').count(),
        'total_value': rfqs.aggregate(total=Sum('req__total'))['total'] or 0,
    })


@procurement_required
def rfq_detail(request, slug):
    rfq = get_object_or_404(RFQ.objects.select_related('req__procurement__project').prefetch_related('supplier', 'send_logs__supplier', 'send_logs__purchase_orders', 'req__items'), slug=slug)
    logs = {log.supplier_id: log for log in rfq.send_logs.all()}
    supplier_rows = []
    for supplier in rfq.supplier.all():
        log = logs.get(supplier.pk)
        po = log.purchase_orders.filter(sent=True).first() if log else None
        supplier_rows.append({'supplier': supplier, 'log': log, 'po': po, 'can_award': bool(log and log.responded)})
    sent_logs = [log for log in logs.values()]
    all_responded = bool(sent_logs) and all(log.responded for log in sent_logs)
    return render(request, 'procurement/rfq_detail.html', {
        'rfq': rfq, 'requisition': rfq.req, 'items': rfq.req.items.all(),
        'supplier_rows': supplier_rows, 'can_send': bool(rfq.file and rfq.status != 'Sent'),
        'all_responded': all_responded,
    })


@procurement_required
def mark_supplier_responded(request, send_log_id):
    if request.method != 'POST':
        return redirect('procurement:rfq_list')
    log = get_object_or_404(RFQSendLog.objects.select_related('rfq'), pk=send_log_id)
    log.responded = True
    log.responded_at = timezone.now()
    log.save(update_fields=['responded', 'responded_at'])
    if log.rfq.send_logs.filter(responded=False).count() == 0:
        log.rfq.status = 'Responded'
        log.rfq.save(update_fields=['status', 'updated_at'])
    messages.success(request, f'{log.supplier.name} has been marked as responded.')
    return redirect('procurement:rfq_detail', slug=log.rfq.slug)


@procurement_required
def mark_all_suppliers_responded(request, slug):
    if request.method != 'POST':
        return redirect('procurement:rfq_detail', slug=slug)
    rfq = get_object_or_404(RFQ, slug=slug)
    now = timezone.now()
    updated = rfq.send_logs.filter(responded=False).update(responded=True, responded_at=now)
    if updated:
        rfq.status = 'Responded'
        rfq.save(update_fields=['status', 'updated_at'])
        messages.success(request, f'{updated} supplier response(s) marked as received.')
    else:
        messages.info(request, 'All sent suppliers are already marked as responded.')
    return redirect('procurement:rfq_detail', slug=rfq.slug)


@procurement_required
def send_rfq_to_supplier(request, slug):
    rfq = get_object_or_404(RFQ.objects.select_related('req').prefetch_related('supplier'), slug=slug)
    if request.method != 'POST':
        return redirect('procurement:rfq_detail', slug=rfq.slug)
    if rfq.status == 'Sent':
        messages.info(request, 'This RFQ has already been sent to the selected suppliers.')
        return redirect('procurement:rfq_detail', slug=rfq.slug)
    if not rfq.file:
        messages.error(request, 'Generate the RFQ PDF before sending it to suppliers.')
        return redirect('procurement:rfq_detail', slug=rfq.slug)
    rfq.file.open('rb')
    attachment = rfq.file.read()
    rfq.file.close()
    sent, errors = [], []
    connection = get_connection()
    try:
        connection.open()
        for supplier in rfq.supplier.all():
            if not supplier.email:
                errors.append(f'{supplier.name} has no email address.')
                continue
            try:
                email = EmailMessage(
                    subject=f'Request for Quotation {rfq.reference_no}',
                    body=(f'Dear {supplier.contact_person or supplier.name},\n\n'
                          f'Please find attached Request for Quotation {rfq.reference_no}.\n'
                          f'Kindly submit your quotation by {rfq.deadline:%d %B %Y}.\n\n'
                          'Regards,\nDDS-NK Procurement Team'),
                    from_email=settings.DEFAULT_FROM_EMAIL, to=[supplier.email], connection=connection,
                )
                email.attach(f'{rfq.reference_no}.pdf', attachment, 'application/pdf')
                email.send()
                RFQSendLog.objects.update_or_create(
                    rfq=rfq, supplier=supplier,
                    defaults={'amount': rfq.req.total, 'request_id': f'rfq-{rfq.pk}-{rfq.deadline}', 'date_sent': timezone.now()},
                )
                sent.append(supplier.name)
            except Exception as error:
                errors.append(f'{supplier.name}: {error}')
    finally:
        connection.close()
    if sent:
        rfq.status = 'Sent'
        rfq.save(update_fields=['status', 'updated_at'])
        messages.success(request, f'RFQ sent to {len(sent)} supplier(s).')
        notify_users(
            request.user.__class__.objects.filter(groups__name__iexact='Procurement', is_active=True).exclude(pk=request.user.pk),
            'RFQ sent to suppliers', f'{rfq.reference_no} was sent to {len(sent)} supplier(s).', url=_rfq_url(rfq), email=False,
        )
    if errors:
        messages.warning(request, 'Some supplier emails failed: ' + '; '.join(errors))
    if not sent:
        messages.error(request, 'No supplier emails were sent.')
    return redirect('procurement:rfq_detail', slug=rfq.slug)


@procurement_required
def rfq_pdf_export(request, slug):
    rfq = get_object_or_404(RFQ, slug=slug)
    if not rfq.file:
        messages.error(request, 'No RFQ PDF is available for download.')
        return redirect('procurement:rfq_detail', slug=rfq.slug)
    with rfq.file.open('rb') as file:
        response = HttpResponse(file.read(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{rfq.reference_no}.pdf"'
    return response


@procurement_required
def rfq_log(request, slug):
    rfq = get_object_or_404(RFQ, slug=slug)
    return render(request, 'procurement/rfq_log.html', {'rfq': rfq, 'logs': rfq.send_logs.select_related('supplier').prefetch_related('purchase_orders')})


@procurement_required
def trash_rfq(request, slug):
    rfq = get_object_or_404(RFQ, slug=slug)
    if request.method == 'POST':
        reference = rfq.reference_no
        rfq.delete()
        messages.success(request, f'{reference} was deleted.')
        return redirect('procurement:rfq_list')
    return render(request, 'procurement/rfq_delete.html', {'rfq': rfq})
