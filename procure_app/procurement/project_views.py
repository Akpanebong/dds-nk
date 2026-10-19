from django.contrib import messages
from django.db.models import Q
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render

from core.access import access_required
from core.utils import stamp_audit
from .forms import ProjectBudgetCreateFormSet, ProjectBudgetFormSet, ProjectForm
from .project_models import Project, ProjectBudget


def default_project_budget_rows():
    fiscal_year = ProjectBudget.current_fiscal_year()
    return [{'fiscal_year': fiscal_year, 'period': period} for period, _ in ProjectBudget.PERIOD_CHOICES]


def save_budget_formset(formset, user):
    """Persist inline budgets while maintaining created/updated audit users."""
    budgets = formset.save(commit=False)
    for budget in budgets:
        stamp_audit(budget, user, creating=budget._state.adding)
        budget.save()
    for budget in formset.deleted_objects:
        budget.delete()
    return budgets


@access_required('procurement')
def project_list(request):
    query = request.GET.get('q', '').strip()
    projects = Project.objects.select_related(
        'project_officer', 'project_head', 'project_accountant'
    ).prefetch_related('budgets')
    if query:
        projects = projects.filter(Q(name__icontains=query) | Q(code__icontains=query) | Q(donor__icontains=query))
    return render(request, 'procurement/project_list.html', {'projects': projects, 'query': query})


@access_required('procurement', manage=True)
def project_create(request):
    form = ProjectForm(request.POST or None)
    formset = ProjectBudgetCreateFormSet(request.POST or None, prefix='budgets', initial=default_project_budget_rows())
    if request.method == 'POST' and form.is_valid() and formset.is_valid():
        with transaction.atomic():
            project = stamp_audit(form.save(commit=False), request.user, creating=True)
            project.save()
            formset.instance = project
            save_budget_formset(formset, request.user)
        messages.success(request, 'Project created successfully.')
        return redirect('procurement:projects')
    return render(request, 'procurement/project_form.html', {'form': form, 'formset': formset, 'title': 'New DDS-NK Project', 'project': None})


@access_required('procurement', manage=True)
def project_update(request, slug):
    project = get_object_or_404(Project, slug=slug)
    form = ProjectForm(request.POST or None, instance=project)
    formset = ProjectBudgetFormSet(request.POST or None, instance=project, prefix='budgets')
    if request.method == 'POST' and form.is_valid() and formset.is_valid():
        with transaction.atomic():
            project = stamp_audit(form.save(commit=False), request.user)
            project.save()
            save_budget_formset(formset, request.user)
        messages.success(request, 'Project updated successfully.')
        return redirect('procurement:projects')
    return render(request, 'procurement/project_form.html', {'form': form, 'formset': formset, 'title': 'Edit DDS-NK Project', 'project': project})


@access_required('procurement', manage=True)
def project_delete(request, slug):
    project = get_object_or_404(Project, slug=slug)
    if request.method == 'POST':
        project.delete()
        messages.success(request, 'Project deleted.')
        return redirect('procurement:projects')
    return render(request, 'procurement/delete_confirmation.html', {'object': project, 'cancel_url': 'procurement:projects', 'title': 'Delete project'})
