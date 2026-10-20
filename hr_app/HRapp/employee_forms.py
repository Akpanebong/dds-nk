from django import forms
from django.forms import inlineformset_factory
from core.models import Department, StaffProfile
from .employee_models import (BankDetail, Dependant, EducationHistory, EmergencyContact,
    EmployeeAddress, EmployeeContact, EmployeePersonalInfo, WorkExperience)
from .employee_models import Employee

class ProfileForm(forms.ModelForm):
    class Meta:
        model = StaffProfile
        fields = [
            'first_name', 'last_name', 'email', 'phone_num',
            'job_title', 'department', 'photo', 'signature',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['department'].queryset = Department.objects.order_by('name')
        for name, field in self.fields.items():
            field.widget.attrs.setdefault('class', 'form-control')
        self.fields['photo'].widget.attrs.update({'accept': 'image/*'})
        self.fields['signature'].widget.attrs.update({'accept': 'image/*,.pdf'})


class StaffProfileCreateForm(ProfileForm):
    """Staff profile form; the initial password is generated server-side."""


class EmployeeRecordForm(forms.ModelForm):
    """Only the supplemental Employee fields retained by this project."""

    class Meta:
        model = Employee
        fields = [
            'supervised_by', 'date_joined', 'user_type', 'status',
            'probation_start_date', 'probation_end_date',
        ]
        widgets = {
            'date_joined': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'probation_start_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'probation_end_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'supervised_by': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.fields['status'].initial = 'Probation'
            self.fields['status'].disabled = True
        probation_required = not self.instance.pk or self.instance.status == 'Probation'
        for name in ('probation_start_date', 'probation_end_date'):
            self.fields[name].required = probation_required

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get('probation_start_date')
        end = cleaned.get('probation_end_date')
        if start and end and end < start:
            self.add_error('probation_end_date', 'Probation end date must be on or after the start date.')
        if cleaned.get('status') == 'Probation':
            if not start:
                self.add_error('probation_start_date', 'Probation start date is required.')
            if not end:
                self.add_error('probation_end_date', 'Probation end date is required.')
        if not self.instance.pk:
            cleaned['status'] = 'Probation'
        return cleaned

class PersonalInfoForm(forms.ModelForm):
    class Meta:
        model = EmployeePersonalInfo
        exclude = ['employee']
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values(): field.required = False

class AddressForm(forms.ModelForm):
    class Meta: model = EmployeeAddress; exclude = ['employee']
class ContactForm(forms.ModelForm):
    class Meta: model = EmployeeContact; exclude = ['employee']
class EmergencyContactForm(forms.ModelForm):
    class Meta: model = EmergencyContact; exclude = ['employee']
class DependantForm(forms.ModelForm):
    class Meta: model = Dependant; exclude = ['employee']
class EducationForm(forms.ModelForm):
    class Meta: model = EducationHistory; exclude = ['employee']
class ExperienceForm(forms.ModelForm):
    class Meta: model = WorkExperience; exclude = ['employee']
class BankForm(forms.ModelForm):
    class Meta: model = BankDetail; exclude = ['employee']
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values(): field.required = False

AddressFormSet = inlineformset_factory(Employee, EmployeeAddress, fk_name='employee', form=AddressForm, extra=1, can_delete=True)
ContactFormSet = inlineformset_factory(Employee, EmployeeContact, fk_name='employee', form=ContactForm, extra=1, can_delete=True)
EmergencyFormSet = inlineformset_factory(Employee, EmergencyContact, fk_name='employee', form=EmergencyContactForm, extra=1, can_delete=True)
DependantFormSet = inlineformset_factory(Employee, Dependant, fk_name='employee', form=DependantForm, extra=1, can_delete=True)
EducationFormSet = inlineformset_factory(Employee, EducationHistory, fk_name='employee', form=EducationForm, extra=1, can_delete=True)
ExperienceFormSet = inlineformset_factory(Employee, WorkExperience, fk_name='employee', form=ExperienceForm, extra=1, can_delete=True)
