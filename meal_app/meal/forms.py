from django import forms
from django.db.models import Q
from .models import ActivityRecord, Indicator, Output, QuarterPlan, StrategicObjective


class BootstrapFormMixin:
    """Apply consistent Bootstrap controls to normal and modal forms."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            existing = field.widget.attrs.get('class', '')
            control = 'form-select' if isinstance(field.widget, (forms.Select, forms.SelectMultiple)) else 'form-control'
            field.widget.attrs['class'] = f'{existing} {control}'.strip()
            field.widget.attrs.setdefault('autocomplete', 'off')


class StrategicObjectiveForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = StrategicObjective
        fields = ['code', 'title', 'description']
        widgets = {'description': forms.Textarea(attrs={'rows': 2})}


class OutputForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Output
        fields = ['objective', 'code', 'title', 'description']
        widgets = {'description': forms.Textarea(attrs={'rows': 2})}


class IndicatorForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Indicator
        fields = ['activity_type', 'code', 'title', 'output', 'indicator_type', 'numerator',
                  'denominator', 'baseline', 'target', 'quarter', 'unit', 'indicator_text',
                  'data_source', 'reporting_frequency', 'responsible', 'notes', 'active']
        labels = {'title': 'Activity', 'baseline': 'Activity baseline', 'target': 'Activity target'}
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 2}),
            'title': forms.TextInput(attrs={'placeholder': 'Enter activity name'}),
        }

ActivityForm = IndicatorForm


class QuarterPlanForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = QuarterPlan
        fields = ['indicator', 'reporting_year', 'quarter', 'target', 'planned_budget', 'budget_expense', 'workbook_result', 'source_row']
        widgets = {
            'reporting_year': forms.NumberInput(attrs={'min': 2020, 'max': 2100}),
            'source_row': forms.NumberInput(attrs={'min': 1}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        queryset = Indicator.objects.filter(active=True)
        if self.instance and self.instance.pk and self.instance.indicator_id:
            queryset = Indicator.objects.filter(Q(active=True) | Q(pk=self.instance.indicator_id))
        self.fields['indicator'].queryset = queryset.select_related('output').order_by('code')

    def clean(self):
        cleaned_data = super().clean()
        indicator = cleaned_data.get('indicator')
        if indicator:
            # Keep the form usable without JavaScript and fill only fields
            # that the user left blank, preserving deliberate overrides.
            if cleaned_data.get('target') is None and indicator.target is not None:
                cleaned_data['target'] = indicator.target
            if not cleaned_data.get('quarter') and indicator.quarter:
                cleaned_data['quarter'] = indicator.quarter
        return cleaned_data


class ActivityRecordBaseForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = ActivityRecord
        fields = ['reporting_year', 'reporting_month', 'status', 'comments']
        widgets = {'reporting_year': forms.NumberInput(attrs={'min': 2020, 'max': 2100}), 'reporting_month': forms.Select(choices=[('', 'Annual / not month-specific')] + [(i, f'{i:02d}') for i in range(1, 13)]), 'comments': forms.Textarea(attrs={'rows': 3})}


class PeopleActivityRecordForm(ActivityRecordBaseForm):
    class Meta(ActivityRecordBaseForm.Meta):
        fields = ActivityRecordBaseForm.Meta.fields + ['women', 'men', 'male_youth', 'female_youth', 'boys', 'girls', 'pwd_male', 'pwd_female']


class NonPeopleActivityRecordForm(ActivityRecordBaseForm):
    class Meta(ActivityRecordBaseForm.Meta):
        fields = ActivityRecordBaseForm.Meta.fields + ['progress_value']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['progress_value'].label = 'Progress/value achieved'
        self.fields['progress_value'].help_text = (
            'Enter the achieved value for this non-people activity. '
            'People activities use their disaggregated participant fields instead.'
        )

    def clean_progress_value(self):
        value = self.cleaned_data['progress_value']
        if value < 0:
            raise forms.ValidationError('Progress cannot be negative.')
        return value
