from django import forms

from .models import Appraisal


class EmployeeAppraisalSubmissionForm(forms.ModelForm):
    class Meta:
        model = Appraisal
        fields = [
            'significant_event',
            'staff_opinion',
            'strengths',
            'weaknesses',
            'capacity_gaps',
            'duty_station',
            'year',
            'years_in_org',
            'filled_appraisal',
        ]
        widgets = {
            'significant_event': forms.Textarea(attrs={'rows': 4, 'class': 'form-control'}),
            'staff_opinion': forms.Textarea(attrs={'rows': 4, 'class': 'form-control'}),
            'strengths': forms.Textarea(attrs={'rows': 4, 'class': 'form-control'}),
            'weaknesses': forms.Textarea(attrs={'rows': 4, 'class': 'form-control'}),
            'capacity_gaps': forms.Textarea(attrs={'rows': 4, 'class': 'form-control'}),
            'duty_station': forms.TextInput(attrs={'class': 'form-control'}),
            'year': forms.NumberInput(attrs={'class': 'form-control'}),
            'years_in_org': forms.TextInput(attrs={'class': 'form-control'}),
            'filled_appraisal': forms.FileInput(attrs={'class': 'form-control'}),
        }


class SupervisorReviewForm(forms.ModelForm):
    class Meta:
        model = Appraisal
        fields = [
            'supervisor_comment',
            'job_description_score',
            'job_description_interpretation',
            'service_score',
            'service_interpretation',
            'filled_appraisal',
        ]
        widgets = {
            'supervisor_comment': forms.Textarea(attrs={'rows': 5, 'class': 'form-control'}),
            'job_description_score': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'max': 100}),
            'job_description_interpretation': forms.TextInput(attrs={'class': 'form-control'}),
            'service_score': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'max': 100}),
            'service_interpretation': forms.TextInput(attrs={'class': 'form-control'}),
            'filled_appraisal': forms.FileInput(attrs={'class': 'form-control'}),
        }


class HRReviewForm(forms.ModelForm):
    class Meta:
        model = Appraisal
        fields = ['hr_comment']
        widgets = {
            'hr_comment': forms.Textarea(attrs={'rows': 6, 'class': 'form-control'}),
        }


class CMTApprovalForm(forms.ModelForm):
    class Meta:
        model = Appraisal
        fields = [
            'cmt_comment',
            'verdict',
            'cmt_signature',
        ]
        widgets = {
            'cmt_comment': forms.Textarea(attrs={'rows': 5, 'class': 'form-control'}),
            'verdict': forms.TextInput(attrs={'class': 'form-control'}),
            'cmt_signature': forms.FileInput(attrs={'class': 'form-control'}),
        }
