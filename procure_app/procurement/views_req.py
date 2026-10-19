from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q, Sum
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.generic import DetailView, ListView
from io import BytesIO
import os
import re

from xhtml2pdf import pisa

from notifications.services import notify_users, notify_user

from .forms import RequisitionForm, RequisitionItemFormSet
from .models import ProcurementPlan, Requisition
from .thresholds import uses_direct_purchase
from .views_rfq import is_procurement_member

User = get_user_model()

def _url(requisition):
    return reverse('procurement:req_detail', kwargs={'slug': requisition.slug})


def _signature_path(user):
    """Return an uploaded staff signature path usable by xhtml2pdf."""
    try:
        return user.signature.path if user and user.signature else ''
    except (AttributeError, ValueError):
        return ''


def _notify(user, title, message, requisition, level='info'):
    if user:
        notify_user(user, title, message, level=level, url=_url(requisition), email=True)


def _ed_users():
    return User.objects.filter(
        Q(groups__name__iexact='ED') | Q(groups__name__iexact='Executive Director'),
        is_active=True,
    ).distinct()


def _reject(requisition, user, reason):
    requisition.status = 'Rejected'
    requisition.rejected_by = user
    requisition.rejected_at = timezone.now()
    requisition.rejection_reason = reason.strip()


def _already_signed(requisition, user):
    return any(
        signer and signer.pk == user.pk
        for signer in (requisition.issued_by, requisition.reviewed_by, requisition.checked_by)
    )


def _item_formset(request, requisition, plan):
    return RequisitionItemFormSet(
        request.POST or None,
        instance=requisition,
        prefix='items',
        plan=plan,
        form_kwargs={'plan': plan},
    )


def _plan_from_form(form, requisition=None):
    if form.is_valid():
        return form.cleaned_data.get('procurement')
    return requisition.procurement if requisition and requisition.procurement_id else None


@login_required
def req_create(request):
    form = RequisitionForm(request.POST or None, user=request.user)
    plan = _plan_from_form(form)
    item_formset = _item_formset(request, Requisition(), plan)
    if request.method == 'POST' and form.is_valid() and item_formset.is_valid():
        with transaction.atomic():
            requisition = form.save(commit=False)
            requisition.issued_by = requisition.created_by = request.user
            requisition.save()
            item_formset.instance = requisition
            item_formset.save()
            requisition.update_total()
        if requisition.project_head:
            _notify(requisition.project_head, 'Requisition awaiting review',
                    f'{requisition.number} for {requisition.project.name} was submitted by {request.user.get_full_name()}.', requisition)
        messages.success(request, f'Requisition {requisition.number} submitted to the Project Head.')
        return redirect('procurement:req_detail', slug=requisition.slug)
    return render(request, 'procurement/req_form.html', {
        'form': form, 'formset': item_formset, 'title': 'New procurement requisition', 'plan': plan,
    })


@login_required
def req_update(request, slug):
    requisition = get_object_or_404(Requisition, slug=slug)
    if requisition.issued_by_id != request.user.id or requisition.status == 'Approved':
        messages.warning(request, 'Only the requester can edit a requisition before final approval.')
        return redirect('procurement:req_detail', slug=requisition.slug)
    form = RequisitionForm(request.POST or None, instance=requisition, user=request.user)
    form_valid = request.method == 'POST' and form.is_valid()
    plan = _plan_from_form(form, requisition)
    plan_changed = bool(form_valid and plan and plan.pk != requisition.procurement_id)
    item_formset = _item_formset(request, Requisition() if plan_changed else requisition, plan)
    if form_valid and item_formset.is_valid():
        requisition = form.save(commit=False)
        requisition.updated_by = request.user
        requisition.status = 'Pending'
        requisition.reviewed_by = requisition.checked_by = requisition.approved_by = None
        requisition.reviewed_at = requisition.checked_at = requisition.approved_at = None
        requisition.rejected_by = requisition.rejected_at = None
        requisition.rejection_reason = ''
        if plan_changed:
            requisition.items.all().delete()
        requisition.save()
        item_formset.instance = requisition
        item_formset.save()
        requisition.update_total()
        _notify(requisition.project_head, 'Requisition awaiting review', f'{requisition.number} was resubmitted for your review.', requisition)
        messages.success(request, f'Requisition {requisition.number} resubmitted.')
        return redirect('procurement:req_detail', slug=requisition.slug)
    return render(request, 'procurement/req_form.html', {
        'form': form, 'formset': item_formset, 'title': 'Edit procurement requisition',
        'requisition': requisition, 'plan': plan,
    })


@login_required
def req_delete(request, slug):
    requisition = get_object_or_404(Requisition, slug=slug)
    if requisition.issued_by_id != request.user.id or requisition.status == 'Approved':
        messages.warning(request, 'Only the requester can delete a requisition before final approval.')
        return redirect('procurement:req_detail', slug=requisition.slug)
    if request.method == 'POST':
        number = requisition.number
        requisition.delete()
        messages.success(request, f'Requisition {number} deleted.')
        return redirect('procurement:req_list')
    return render(request, 'procurement/delete_confirmation.html', {
        'object': requisition,
        'title': 'Delete procurement requisition',
        'cancel_url': 'procurement:req_detail',
        'cancel_slug': requisition.slug,
    })


@login_required
def req_plan_items(request, slug):
    plan = get_object_or_404(ProcurementPlan, slug=slug, status=ProcurementPlan.APPROVED)
    is_existing_requester = plan.requisitions.filter(issued_by=request.user).exists()
    if not request.user.is_superuser and plan.project.project_officer_id != request.user.id and not is_existing_requester:
        return JsonResponse({'detail': 'You cannot use this procurement plan.'}, status=403)
    committed = plan.requisitions.exclude(status='Rejected').aggregate(total=Sum('total'))['total'] or 0
    return JsonResponse({
        'budget': str(plan.budget),
        'committed': str(committed),
        'items': [
            {
                'id': item.pk,
                'description': item.description or item.product.name,
                'product': item.product.name,
                'qty': str(item.qty),
                'unit_measure': item.unit_measure or item.product.get_unit_display(),
                'unit_price': str(item.est_unit_cost),
                'delivery_date': item.delivery_date.isoformat() if item.delivery_date else '',
            }
            for item in plan.items.select_related('product').order_by('id')
        ],
    })


@login_required
def req_pdf_export(request, slug):
    """Download the official PDF record after ED approval."""
    requisition = get_object_or_404(
        Requisition.objects.select_related(
            'procurement__project', 'issued_by', 'reviewed_by',
            'checked_by', 'approved_by',
        ).prefetch_related('items__procurement_item__product'),
        slug=slug,
    )

    user = request.user
    is_ed = user.groups.filter(
        Q(name__iexact='ED') | Q(name__iexact='Executive Director')
    ).exists()
    project = requisition.project
    allowed = user.is_superuser or is_ed or user in {
        requisition.issued_by,
        project.project_head if project else None,
        project.project_accountant if project else None,
    }
    if not allowed:
        messages.warning(request, 'You do not have access to this requisition.')
        return redirect('procurement:req_list')

    if requisition.status != 'Approved':
        messages.warning(request, 'The official PDF is available after ED approval.')
        return redirect('procurement:req_detail', slug=requisition.slug)

    logo_path = os.path.join(settings.BASE_DIR, 'static', 'img', 'dds_nk.jpg')
    html = render_to_string('procurement/requisition_pdf.html', {
        'requisition': requisition,
        'logo_path': logo_path,
        'requester_signature': _signature_path(requisition.issued_by),
        'reviewer_signature': _signature_path(requisition.reviewed_by),
        'checker_signature': _signature_path(requisition.checked_by),
        'approver_signature': _signature_path(requisition.approved_by),
        'generated_at': timezone.now(),
    })
    output = BytesIO()
    result = pisa.CreatePDF(BytesIO(html.encode('utf-8')), dest=output)
    if result.err:
        messages.error(request, 'The approved requisition PDF could not be generated. Please try again.')
        return redirect('procurement:req_detail', slug=requisition.slug)

    safe_number = re.sub(r'[^A-Za-z0-9_-]+', '-', requisition.number).strip('-') or 'requisition'
    response = HttpResponse(output.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="DDS-NK_Procurement_Requisition_{safe_number}.pdf"'
    return response


@login_required
def req_approve(request, slug):
    requisition = get_object_or_404(Requisition, slug=slug)
    if request.method != 'POST':
        return redirect('procurement:req_detail', slug=requisition.slug)
    user, action = request.user, request.POST.get('action', '').lower()
    reason = request.POST.get('reason', '').strip()
    project = requisition.project
    is_ed = user.groups.filter(Q(name__iexact='ED') | Q(name__iexact='Executive Director')).exists()

    if user == requisition.project_head and requisition.status == 'Pending' and not _already_signed(requisition, user):
        if action == 'review':
            requisition.reviewed_by, requisition.reviewed_at, requisition.status = user, timezone.now(), 'Reviewed'
            _notify(requisition.project_accountant, 'Requisition awaiting financial check', f'{requisition.number} requires your financial check.', requisition)
            _notify(requisition.issued_by, 'Requisition reviewed by Project Head', f'{requisition.number} has been reviewed and sent to the Project Accountant.', requisition)
        elif action == 'reject':
            _reject(requisition, user, reason)
            _notify(requisition.issued_by, 'Requisition returned by Project Head', f'{requisition.number} was returned for revision. Reason: {reason}', requisition, 'warning')
        else:
            messages.error(request, 'Choose Review or Reject.')
            return redirect('procurement:req_detail', slug=requisition.slug)
    elif user == requisition.project_accountant and requisition.status == 'Reviewed' and not _already_signed(requisition, user):
        if action == 'check':
            requisition.checked_by, requisition.checked_at, requisition.status = user, timezone.now(), 'Checked'
            notify_users(_ed_users(), 'Requisition awaiting ED approval', f'{requisition.number} for {project.name} requires approval.', url=_url(requisition), email=True)
            _notify(requisition.issued_by, 'Requisition checked by Project Accountant', f'{requisition.number} passed the financial check and is awaiting ED approval.', requisition)
        elif action == 'reject':
            _reject(requisition, user, reason)
            _notify(requisition.issued_by, 'Requisition returned by Project Accountant', f'{requisition.number} was returned for revision. Reason: {reason}', requisition, 'warning')
        else:
            messages.error(request, 'Choose Check or Reject.')
            return redirect('procurement:req_detail', slug=requisition.slug)
    elif is_ed and requisition.status == 'Checked' and not _already_signed(requisition, user):
        if action == 'approve':
            requisition.approved_by, requisition.approved_at, requisition.status = user, timezone.now(), 'Approved'
            _notify(requisition.issued_by, 'Requisition approved', f'{requisition.number} was approved by the Executive Director.', requisition, 'success')
        elif action == 'reject':
            _reject(requisition, user, reason)
            _notify(requisition.issued_by, 'Requisition rejected by Executive Director', f'{requisition.number} was rejected. Reason: {reason}', requisition, 'error')
        else:
            messages.error(request, 'Choose Approve or Reject.')
            return redirect('procurement:req_detail', slug=requisition.slug)
    else:
        messages.warning(request, 'You are not authorised to act at this stage of the workflow.')
        return redirect('procurement:req_detail', slug=requisition.slug)

    requisition.updated_by = user
    requisition.save()
    messages.success(request, f'Requisition {requisition.number} updated: {requisition.status}.')
    return redirect('procurement:req_detail', slug=requisition.slug)


@method_decorator(login_required, name='dispatch')
class RequisitionListView(ListView):
    model = Requisition
    template_name = 'procurement/req_list.html'
    context_object_name = 'requisitions'
    paginate_by = 25

    def get_queryset(self):
        qs = Requisition.objects.select_related('procurement__project', 'issued_by').prefetch_related('items').order_by('-date', '-id')
        if not self.request.user.is_superuser:
            user = self.request.user
            is_ed = user.groups.filter(Q(name__iexact='ED') | Q(name__iexact='Executive Director')).exists()
            visibility = Q(issued_by=user) | Q(procurement__project__project_head=user) | Q(procurement__project__project_accountant=user)
            if is_ed:
                visibility |= Q(status='Checked')
            qs = qs.filter(visibility).distinct()
        if self.request.GET.get('status'):
            qs = qs.filter(status=self.request.GET['status'])
        if self.request.GET.get('search'):
            term = self.request.GET['search']
            qs = qs.filter(Q(number__icontains=term) | Q(procurement__project__name__icontains=term) | Q(status__icontains=term))
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        qs = self.get_queryset()
        context.update(approved_count=qs.filter(status='Approved').count(), pending_count=qs.filter(status__in=['Pending', 'Reviewed', 'Checked']).count(), rejected_count=qs.filter(status='Rejected').count(), grand_total=qs.aggregate(total=Sum('total'))['total'] or 0)
        return context


@method_decorator(login_required, name='dispatch')
class RequisitionDetailView(DetailView):
    model = Requisition
    slug_field = 'slug'
    slug_url_kwarg = 'slug'
    template_name = 'procurement/req_detail.html'
    context_object_name = 'requisition'

    def get_queryset(self):
        return Requisition.objects.select_related('procurement__project', 'issued_by', 'reviewed_by', 'checked_by', 'approved_by', 'rejected_by').prefetch_related('items')

    def dispatch(self, request, *args, **kwargs):
        requisition = get_object_or_404(Requisition, slug=kwargs['slug'])
        user = request.user
        is_ed = user.groups.filter(Q(name__iexact='ED') | Q(name__iexact='Executive Director')).exists()
        project = requisition.project
        allowed = user.is_superuser or is_ed or user in {requisition.issued_by, project.project_head, project.project_accountant}
        if not allowed:
            messages.warning(request, 'You do not have access to this project requisition.')
            return redirect('procurement:req_list')
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        requisition = self.object
        context['stages'] = [('Project Officer', requisition.issued_by, requisition.created_at), ('Project Head review', requisition.reviewed_by, requisition.reviewed_at), ('Project Accountant check', requisition.checked_by, requisition.checked_at), ('Executive Director approval', requisition.approved_by, requisition.approved_at)]
        completed_stages = sum(bool(value) for value in (requisition.issued_by, requisition.reviewed_by, requisition.checked_by, requisition.approved_by))
        context['progress_percent'] = round((completed_stages / 4) * 100)
        context['can_act'] = ((self.request.user == requisition.project_head and requisition.status == 'Pending') or (self.request.user == requisition.project_accountant and requisition.status == 'Reviewed') or (self.request.user.groups.filter(Q(name__iexact='ED') | Q(name__iexact='Executive Director')).exists() and requisition.status == 'Checked'))
        context['can_edit'] = self.request.user == requisition.issued_by and requisition.status != 'Approved'
        context['can_delete'] = context['can_edit']
        context['can_download_pdf'] = requisition.status == 'Approved'
        procurement_user = is_procurement_member(self.request.user)
        context['can_direct_purchase'] = context['can_download_pdf'] and procurement_user and uses_direct_purchase(requisition.total)
        context['can_create_rfq'] = context['can_download_pdf'] and procurement_user and not uses_direct_purchase(requisition.total)
        return context
