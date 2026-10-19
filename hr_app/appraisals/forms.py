from django import forms
from .models import Goal, KPI, Appraisal, AppraisalReview


class GoalForm(forms.ModelForm):
    class Meta:
        model = Goal
        fields = ['title', 'start_date', 'end_date', 'description']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'rows': 4, 'class': 'form-control'}),
            'start_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'end_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            # 'employee': forms.Select(attrs={'class': 'form-control'}),
        }


class KPIForm(forms.ModelForm):
    class Meta:
        model = KPI
        fields = ['name', 'target_value', 'actual_value', 'unit']


class AppraisalForm(forms.ModelForm):

    class Meta:
        model = Appraisal
        fields = ['appraisal_type', 'status']
        widgets = {
            'appraisal_type': forms.Select(attrs={'class': 'form-select'}),
            'status': forms.Select(attrs={'class': 'form-select'})
        }


class AppraisalReviewForm(forms.ModelForm):

    class Meta:
        model = AppraisalReview
        fields = ['role', 'rating', 'comments']
        widgets = {
            'role': forms.Select(attrs={'class': 'form-select'}),
            'rating': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': 1,
                'max': 5
            }),
            'comments': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Provide structured performance feedback...'
            }),
        }
