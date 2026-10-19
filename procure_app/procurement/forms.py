from decimal import Decimal, ROUND_DOWN

from django import forms
from django.db.models import Q, Sum
from django.forms import inlineformset_factory
from django.utils import timezone

from .models import (
    Product, ProcurementPlan, ProcurementPlanItem, PurchaseOrder,
    Requisition, RequisitionItem, RFQ, Supplier,
)
from .project_models import Project, ProjectBudget


class StyledModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'form-control')
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs['class'] = 'form-check-input'


class SupplierForm(StyledModelForm):
    class Meta:
        model = Supplier
        exclude = ('slug', 'created_by', 'updated_by')
        widgets = {'address': forms.Textarea(attrs={'rows': 2}), 'notes': forms.Textarea(attrs={'rows': 2})}


class ProductForm(StyledModelForm):
    class Meta:
        model = Product
        fields = ('code', 'name', 'description', 'category', 'other_category', 'unit', 'est_unit_cost', 'active')
        widgets = {'description': forms.Textarea(attrs={'rows': 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['category'].widget.attrs['class'] += ' product-category'
        self.fields['other_category'].widget.attrs['class'] += ' product-other-category'

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('category') == 'OTHER' and not (cleaned.get('other_category') or '').strip():
            self.add_error('other_category', 'Specify the product category.')
        elif cleaned.get('category') != 'OTHER':
            cleaned['other_category'] = ''
        return cleaned


class ProjectForm(StyledModelForm):
    class Meta:
        model = Project
        fields = ('code', 'name', 'description', 'donor', 'status', 'projected_reach',
                  'project_head', 'project_accountant', 'project_officer',
                  'start_date', 'end_date', 'location',)
        widgets = {
            'description': forms.Textarea(attrs={'rows': 2}),
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
            'location': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('start_date') and cleaned.get('end_date') and cleaned['end_date'] < cleaned['start_date']:
            self.add_error('end_date', 'End date must be on or after the start date.')
        return cleaned


class ProjectBudgetForm(StyledModelForm):
    class Meta:
        model = ProjectBudget
        fields = ('fiscal_year', 'period', 'budget_amount')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['budget_amount'].required = False
        self.fields['budget_amount'].widget.attrs.update({'min': '0', 'step': '0.01', 'class': 'form-control budget-amount'})


class ProjectBudgetFormSetBase(forms.BaseInlineFormSet):
    """Validate and, when needed, distribute the annual budget over Q1-Q4."""

    def clean(self):
        super().clean()
        if any(self.errors):
            return

        forms_by_period = {}
        for form in self.forms:
            if not form.cleaned_data or form.cleaned_data.get('DELETE'):
                continue
            period = form.cleaned_data.get('period')
            if period:
                forms_by_period[period] = form

        annual_form = forms_by_period.get(ProjectBudget.FULL_YEAR)
        annual = annual_form.cleaned_data.get('budget_amount') if annual_form else None
        if annual is None:
            return

        quarter_periods = [ProjectBudget.Q1, ProjectBudget.Q2, ProjectBudget.Q3, ProjectBudget.Q4]
        quarter_forms = [forms_by_period.get(period) for period in quarter_periods]
        entered_quarters = [form.cleaned_data.get('budget_amount') for form in quarter_forms if form]
        if not entered_quarters or all(value in (None, '') for value in entered_quarters):
            share = (annual / Decimal('4')).quantize(Decimal('0.01'), rounding=ROUND_DOWN)
            values = [share, share, share, share]
            for form, value in zip(quarter_forms, values):
                if form:
                    form.cleaned_data['budget_amount'] = value


ProjectBudgetFormSet = inlineformset_factory(
    Project,
    ProjectBudget,
    form=ProjectBudgetForm,
    formset=ProjectBudgetFormSetBase,
    extra=0,
    can_delete=True,
)

# New projects still receive the standard annual and quarterly budget rows.
# Existing projects should render only the budget records already saved.
ProjectBudgetCreateFormSet = inlineformset_factory(
    Project,
    ProjectBudget,
    form=ProjectBudgetForm,
    formset=ProjectBudgetFormSetBase,
    extra=5,
    can_delete=True,
)


class ProcurementPlanForm(StyledModelForm):
    class Meta:
        model = ProcurementPlan
        fields = ('number', 'project', 'fiscal_year', 'budget_period', 'donor', 'budget')

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            project_queryset = Project.objects.filter(project_head=user)
            if self.instance and self.instance.project_id:
                project_queryset = Project.objects.filter(Q(pk=self.instance.project_id) | Q(project_head=user))
            self.fields['project'].queryset = project_queryset.distinct().order_by('name')
        self.fields['fiscal_year'].initial = self.fields['fiscal_year'].initial or ProjectBudget.current_fiscal_year()
        self.fields['donor'].widget.attrs.update({'readonly': 'readonly', 'class': 'form-control plan-readonly'})
        self.fields['budget'].required = False
        self.fields['budget'].widget.attrs.update({'readonly': 'readonly', 'class': 'form-control plan-readonly', 'inputmode': 'decimal'})

    def clean(self):
        cleaned = super().clean()
        project = cleaned.get('project')
        fiscal_year = cleaned.get('fiscal_year')
        period = cleaned.get('budget_period') or ProjectBudget.FULL_YEAR
        if project and fiscal_year:
            budget = ProjectBudget.objects.filter(project=project, fiscal_year=fiscal_year, period=period).first()
            if not budget and period != ProjectBudget.FULL_YEAR:
                budget = ProjectBudget.objects.filter(project=project, fiscal_year=fiscal_year, period=ProjectBudget.FULL_YEAR).first()
            if not budget:
                raise forms.ValidationError('No matching project budget exists for this fiscal year and period.')
            cleaned['budget'] = budget.budget_amount
            cleaned['donor'] = project.donor
        return cleaned


class ProcurementPlanItemForm(StyledModelForm):
    class Meta:
        model = ProcurementPlanItem
        fields = ('product', 'description', 'qty', 'est_unit_cost', 'unit_measure', 'delivery_date')
        labels = {'est_unit_cost': 'Unit price'}
        widgets = {'delivery_date': forms.DateInput(attrs={'type': 'date'})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['description'].required = False
        self.fields['unit_measure'].required = False
        if not self.instance.pk:
            self.fields['unit_measure'].initial = ''
        self.fields['est_unit_cost'].required = False
        self.fields['delivery_date'].required = True
        self.fields['delivery_date'].widget.attrs['required'] = 'required'
        self.fields['est_unit_cost'].widget.attrs.update({'min': '0', 'step': '0.01', 'class': 'form-control item-unit-price'})
        self.fields['qty'].widget.attrs.update({'min': '0', 'step': '0.01', 'class': 'form-control item-quantity'})

    def clean(self):
        cleaned = super().clean()
        product = cleaned.get('product')
        if product:
            if cleaned.get('est_unit_cost') in (None, ''):
                cleaned['est_unit_cost'] = product.est_unit_cost
            if not cleaned.get('description'):
                cleaned['description'] = product.name
            if not cleaned.get('unit_measure'):
                cleaned['unit_measure'] = product.get_unit_display()
        return cleaned


class ProcurementPlanItemFormSetBase(forms.BaseInlineFormSet):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for form in self.forms:
            if 'DELETE' in form.fields:
                form.fields['DELETE'].widget.attrs['class'] = 'item-delete-input visually-hidden'

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        if not any(form.cleaned_data and not form.cleaned_data.get('DELETE') for form in self.forms):
            raise forms.ValidationError('Add at least one procurement item before submitting.')


ProcurementPlanItemFormSet = inlineformset_factory(
    ProcurementPlan,
    ProcurementPlanItem,
    form=ProcurementPlanItemForm,
    formset=ProcurementPlanItemFormSetBase,
    extra=1,
    can_delete=True,
)


VendorForm = SupplierForm


class RequisitionForm(StyledModelForm):
    class Meta:
        model = Requisition
        fields = ('number', 'procurement', 'activity_name', 'date')
        widgets = {'date': forms.DateInput(attrs={'type': 'date'})}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['procurement'].required = True
        self.fields['procurement'].to_field_name = 'slug'
        plans = ProcurementPlan.objects.filter(status=ProcurementPlan.APPROVED).select_related('project')
        if user is not None and not user.is_superuser:
            if self.instance and self.instance.pk and self.instance.procurement_id:
                plans = plans.filter(Q(project__project_officer=user) | Q(pk=self.instance.procurement_id))
            else:
                plans = plans.filter(project__project_officer=user)
        self.fields['procurement'].queryset = plans.order_by('project__name', 'number')
        if self.instance and self.instance.pk and self.instance.procurement:
            self.initial['procurement'] = self.instance.procurement.slug

    def clean(self):
        cleaned = super().clean()
        plan = cleaned.get('procurement')
        if plan and plan.status != ProcurementPlan.APPROVED:
            raise forms.ValidationError('A requisition can only be raised against an approved procurement plan.')
        if plan and plan.project_id and not plan.project.project_officer_id:
            raise forms.ValidationError('The selected project has no assigned Project Officer.')
        if plan and plan.project_id and not plan.project.project_head_id:
            raise forms.ValidationError('The selected project has no assigned Project Head.')
        if plan and plan.project_id and not plan.project.project_accountant_id:
            raise forms.ValidationError('The selected project has no assigned Project Accountant.')
        return cleaned


class RequisitionItemForm(StyledModelForm):
    class Meta:
        model = RequisitionItem
        fields = ('procurement_item', 'description', 'qty', 'unit_measure', 'unit_price', 'delivery_date')
        widgets = {
            'description': forms.TextInput(),
            'unit_measure': forms.TextInput(),
            'unit_price': forms.NumberInput(attrs={'min': '0', 'step': '0.01'}),
            'delivery_date': forms.DateInput(attrs={'type': 'date'}),
            'qty': forms.NumberInput(attrs={'min': '0.01', 'step': '0.01'}),
        }

    def __init__(self, *args, plan=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.plan = plan
        self.fields['procurement_item'].queryset = (
            ProcurementPlanItem.objects.filter(procurement=plan).select_related('product')
            if plan else ProcurementPlanItem.objects.none()
        )
        self.fields['procurement_item'].required = True

    def clean(self):
        cleaned = super().clean()
        item = cleaned.get('procurement_item')
        if not item:
            return cleaned
        qty = cleaned.get('qty')
        if qty is None or qty <= 0:
            self.add_error('qty', 'Enter a quantity greater than zero.')
            return cleaned
        if qty > item.qty:
            self.add_error('qty', f'Quantity cannot exceed the approved plan quantity of {item.qty}.')
        if not (cleaned.get('description') or '').strip():
            self.add_error('description', 'Enter a description for this requisition item.')
        if cleaned.get('unit_price') is None or cleaned['unit_price'] < 0:
            self.add_error('unit_price', 'Enter a valid non-negative unit price.')
        if not cleaned.get('delivery_date'):
            self.add_error('delivery_date', 'Enter a delivery date.')
        return cleaned


class RequisitionItemFormSetBase(forms.BaseInlineFormSet):
    def __init__(self, *args, plan=None, **kwargs):
        self.plan = plan
        super().__init__(*args, **kwargs)

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        selected = []
        total = Decimal('0.00')
        for form in self.forms:
            if not form.cleaned_data or form.cleaned_data.get('DELETE'):
                continue
            item = form.cleaned_data.get('procurement_item')
            if not item:
                continue
            if item.pk in selected:
                raise forms.ValidationError('Each procurement plan item may only be selected once.')
            selected.append(item.pk)
            requested_qty = form.cleaned_data['qty']
            previously_requested = RequisitionItem.objects.filter(
                po__procurement=self.plan,
                procurement_item=item,
            ).exclude(po__status='Rejected')
            if self.instance.pk:
                previously_requested = previously_requested.exclude(po=self.instance)
            previously_requested = previously_requested.aggregate(total=Sum('qty'))['total'] or Decimal('0.00')
            if previously_requested + requested_qty > item.qty:
                raise forms.ValidationError(
                    f'{item.description} has only {max(item.qty - previously_requested, Decimal("0.00"))} '
                    f'available from the approved plan.'
                )
            total += requested_qty * form.cleaned_data['unit_price']

        if not selected:
            raise forms.ValidationError('Select at least one item from the approved procurement plan.')
        if not self.plan:
            raise forms.ValidationError('Select an approved procurement plan first.')

        committed = self.plan.requisitions.exclude(status='Rejected')
        if self.instance.pk:
            committed = committed.exclude(pk=self.instance.pk)
        already_requested = committed.aggregate(total=Sum('total'))['total'] or Decimal('0.00')
        if already_requested + total > self.plan.budget:
            remaining = self.plan.budget - already_requested
            raise forms.ValidationError(
                f'This requisition totals {total:,.2f}, but only {max(remaining, Decimal("0.00")):,.2f} '
                f'remains from the approved plan budget of {self.plan.budget:,.2f}.'
            )


RequisitionItemFormSet = inlineformset_factory(
    Requisition,
    RequisitionItem,
    form=RequisitionItemForm,
    formset=RequisitionItemFormSetBase,
    extra=0,
    can_delete=True,
)


class RFQForm(StyledModelForm):
    """Procurement-only form for issuing a quotation request."""

    class Meta:
        model = RFQ
        fields = ('supplier', 'deadline')
        widgets = {'deadline': forms.DateInput(attrs={'type': 'date'})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['supplier'].queryset = Supplier.objects.filter(
            active=True,
        ).order_by('name')
        self.fields['supplier'].required = True
        self.fields['supplier'].widget.attrs.update({'class': 'form-select', 'size': 8})
        self.fields['deadline'].required = True

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('deadline') and cleaned['deadline'] < timezone.now().date():
            self.add_error('deadline', 'The supplier response deadline cannot be in the past.')
        if not cleaned.get('supplier'):
            self.add_error('supplier', 'Select at least one supplier.')
        return cleaned


class PurchaseOrderForm(StyledModelForm):
    """Fields procurement must complete when awarding an RFQ supplier."""

    class Meta:
        model = PurchaseOrder
        fields = ('final_amount', 'due_date', 'remarks')
        widgets = {
            'final_amount': forms.NumberInput(attrs={'min': '0', 'step': '0.01'}),
            'due_date': forms.DateInput(attrs={'type': 'date'}),
            'remarks': forms.Textarea(attrs={'rows': 4}),
        }

    def __init__(self, *args, supplier=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.supplier = supplier
        self.fields['final_amount'].required = True
        self.fields['due_date'].required = True

    def clean_final_amount(self):
        amount = self.cleaned_data.get('final_amount')
        if amount is None or amount <= 0:
            raise forms.ValidationError('Enter a quoted amount greater than zero.')
        return amount


class DirectPurchaseForm(forms.Form):
    """Single-quotation supplier and order details for petty-cash purchases."""

    supplier = forms.ModelChoiceField(
        queryset=Supplier.objects.filter(active=True).order_by('name'),
        empty_label='Select supplier',
    )
    final_amount = forms.DecimalField(min_value=Decimal('0.01'), max_digits=15, decimal_places=2)
    due_date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
    remarks = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 4}))

    def __init__(self, *args, requisition=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.requisition = requisition
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'form-control')

    def clean_final_amount(self):
        amount = self.cleaned_data['final_amount']
        if self.requisition and amount > self.requisition.total:
            raise forms.ValidationError('The direct purchase amount cannot exceed the approved requisition total.')
        return amount
