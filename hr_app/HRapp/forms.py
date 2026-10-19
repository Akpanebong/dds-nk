from notifications.models import Notification
from .models import Leave, LeaveSchedule, Attendance, Training, SituationReport
from django import forms
from django.forms import inlineformset_factory
from .employee_models import (
    BankDetail,
    Dependant,
    EducationHistory,
    EmergencyContact,
    Employee,
    EmployeeAddress,
    EmployeeContact,
    EmployeePersonalInfo,
    WorkExperience,
)
from .orientation_models import OrientationPlan, OrientationSession
from core.models import Department, StaffProfile
Profile = StaffProfile


class EmployeeForm(forms.ModelForm):

    class Meta:
        model = Employee
        fields = ['job_title', 'staff_reg_no', 'supervised_by', 'date_joined',
                  ]
        widgets = {
            'district': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter district'
            }),
            'address': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter Employee Address'
            }),
            'city': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter Employee City.'
            }),
            'postal_code': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter Employee Postal code'
            }),
            'job_title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter job title'
            }),
            'staff_reg_no': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter Staff ID'
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter phone number'
            }),
            'date_joined': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date'
            }),
        }



class EmployeeUpdateForm(forms.ModelForm):
    class Meta:
        model = Employee
        fields = [
            "staff_reg_no",
            "job_title",
            "supervised_by",
            "date_joined",
        ]
        widgets = {
            "date_joined": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        readonly_fields = set(kwargs.pop("readonly_fields", ()))
        super().__init__(*args, **kwargs)

        for name, field in self.fields.items():
            field.widget.attrs.update({'class': 'form-control'})
            if name in readonly_fields:
                field.disabled = True
                field.widget.attrs.update({
                    "class": f"{field.widget.attrs.get('class', '')} bg-light text-muted".strip(),
                    "aria-readonly": "true",
                })

        self.fields['job_title'].widget.attrs.update({'placeholder': 'e.g. Software Engineer'})
        self.fields['staff_reg_no'].widget.attrs.update({'placeholder': 'e.g. EMP-001'})

    def get_groups(self):
        return {
            "Employment": ["staff_reg_no", "job_title", "supervised_by", "date_joined"],
        }


class EmployeePersonalInfoForm(forms.ModelForm):
    class Meta:
        model = EmployeePersonalInfo
        exclude = ("employee",)
        widgets = {
            "date_of_birth": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.required = False


class EmployeeAddressForm(forms.ModelForm):
    class Meta:
        model = EmployeeAddress
        exclude = ("employee",)
        widgets = {
            "address": forms.Textarea(attrs={"rows": 2}),
        }


class EmployeeContactForm(forms.ModelForm):
    class Meta:
        model = EmployeeContact
        exclude = ("employee",)


class EmergencyContactForm(forms.ModelForm):
    class Meta:
        model = EmergencyContact
        exclude = ("employee",)
        widgets = {
            "address": forms.Textarea(attrs={"rows": 2}),
        }


class DependantForm(forms.ModelForm):
    class Meta:
        model = Dependant
        exclude = ("employee",)
        widgets = {
            "date_of_birth": forms.DateInput(attrs={"type": "date"}),
        }


class EducationHistoryForm(forms.ModelForm):
    class Meta:
        model = EducationHistory
        exclude = ("employee",)
        widgets = {
            "certifications": forms.Textarea(attrs={"rows": 2}),
        }


class WorkExperienceForm(forms.ModelForm):
    class Meta:
        model = WorkExperience
        exclude = ("employee",)
        widgets = {
            "skills": forms.Textarea(attrs={"rows": 2}),
            "years": forms.NumberInput(attrs={"type": "year"}),

        }


class BankDetailForm(forms.ModelForm):
    class Meta:
        model = BankDetail
        exclude = ("employee",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.required = False


EMPLOYEE_SINGLE_FORM_CLASSES = {
    "personal_info_form": EmployeePersonalInfoForm,
    "bank_detail_form": BankDetailForm,
}


EMPLOYEE_FORMSET_CLASSES = {
    "address_formset": inlineformset_factory(
        Employee,
        EmployeeAddress,
        form=EmployeeAddressForm,
        extra=1,
        can_delete=True,
    ),
    "contact_formset": inlineformset_factory(
        Employee,
        EmployeeContact,
        form=EmployeeContactForm,
        extra=1,
        can_delete=True,
    ),
    "emergency_contact_formset": inlineformset_factory(
        Employee,
        EmergencyContact,
        form=EmergencyContactForm,
        extra=1,
        can_delete=True,
    ),
    "dependant_formset": inlineformset_factory(
        Employee,
        Dependant,
        form=DependantForm,
        extra=1,
        can_delete=True,
    ),
    "education_history_formset": inlineformset_factory(
        Employee,
        EducationHistory,
        form=EducationHistoryForm,
        extra=1,
        can_delete=True,
    ),
    "work_experience_formset": inlineformset_factory(
        Employee,
        WorkExperience,
        form=WorkExperienceForm,
        extra=1,
        can_delete=True,
    ),
}


def style_employee_profile_forms(forms_or_formsets):
    for item in forms_or_formsets:
        forms = item.forms if hasattr(item, "forms") else [item]
        for form in forms:
            for field in form.fields.values():
                if field.widget.__class__.__name__ == "CheckboxInput":
                    field.widget.attrs.update({"class": "form-check-input"})
                elif field.widget.__class__.__name__ == "Select":
                    field.widget.attrs.update({"class": "form-select"})
                else:
                    field.widget.attrs.update({"class": "form-control"})


def get_employee_profile_form_sections(*, post_data=None, files=None, employee=None):
    personal_info = EmployeePersonalInfo.objects.filter(employee=employee).first()
    bank_detail = BankDetail.objects.filter(employee=employee).first()

    form_kwargs = {"data": post_data, "files": files} if post_data is not None else {}

    single_forms = {
        "personal_info_form": EmployeePersonalInfoForm(
            **form_kwargs,
            instance=personal_info,
            prefix="personal",
        ),
        "bank_detail_form": BankDetailForm(
            **form_kwargs,
            instance=bank_detail,
            prefix="bank",
        ),
    }

    formsets = {
        "address_formset": EMPLOYEE_FORMSET_CLASSES["address_formset"](
            post_data,
            files,
            instance=employee,
            prefix="addresses",
        ),
        "contact_formset": EMPLOYEE_FORMSET_CLASSES["contact_formset"](
            post_data,
            files,
            instance=employee,
            prefix="contacts",
        ),
        "emergency_contact_formset": EMPLOYEE_FORMSET_CLASSES["emergency_contact_formset"](
            post_data,
            files,
            instance=employee,
            prefix="emergency",
        ),
        "dependant_formset": EMPLOYEE_FORMSET_CLASSES["dependant_formset"](
            post_data,
            files,
            instance=employee,
            prefix="dependants",
        ),
        "education_history_formset": EMPLOYEE_FORMSET_CLASSES["education_history_formset"](
            post_data,
            files,
            instance=employee,
            prefix="education",
        ),
        "work_experience_formset": EMPLOYEE_FORMSET_CLASSES["work_experience_formset"](
            post_data,
            files,
            instance=employee,
            prefix="experience",
        ),
    }

    style_employee_profile_forms([*single_forms.values(), *formsets.values()])

    sections = [
        {
            "key": "personal",
            "number": "03",
            "title": "Personal Information",
            "description": "Bio data, identity numbers, and demographic information.",
            "icon": "fa-user-check",
            "form": single_forms["personal_info_form"],
        },
        {
            "key": "addresses",
            "number": "04",
            "title": "Addresses",
            "description": "Permanent, present, and office address records.",
            "icon": "fa-location-dot",
            "formset": formsets["address_formset"],
        },
        {
            "key": "contacts",
            "number": "05",
            "title": "Contact Channels",
            "description": "Personal, official, and home phone or email details.",
            "icon": "fa-address-book",
            "formset": formsets["contact_formset"],
        },
        {
            "key": "emergency",
            "number": "06",
            "title": "Emergency Contacts",
            "description": "People HR can contact in urgent situations.",
            "icon": "fa-kit-medical",
            "formset": formsets["emergency_contact_formset"],
        },
        {
            "key": "dependants",
            "number": "07",
            "title": "Dependants",
            "description": "Dependants attached to this employee profile.",
            "icon": "fa-people-roof",
            "formset": formsets["dependant_formset"],
        },
        {
            "key": "education",
            "number": "08",
            "title": "Education History",
            "description": "Academic qualifications and certifications.",
            "icon": "fa-graduation-cap",
            "formset": formsets["education_history_formset"],
        },
        {
            "key": "experience",
            "number": "09",
            "title": "Work Experience",
            "description": "Previous employers, positions, years, and skills.",
            "icon": "fa-briefcase",
            "formset": formsets["work_experience_formset"],
        },
        {
            "key": "banking",
            "number": "10",
            "title": "Banking Details",
            "description": "Payroll account and bank branch information.",
            "icon": "fa-building-columns",
            "form": single_forms["bank_detail_form"],
        },
    ]

    return single_forms, formsets, sections


class ProfileForm(forms.ModelForm):

    department = forms.ModelChoiceField(
        queryset=Department.objects.exclude(name='ED'),
        empty_label='--Choose Department--',
        help_text='Click <a target="_blank" href="/departments/create/">Add Department</a>'
    )

    class Meta:
        model = Profile
        fields = [
            'first_name', 'last_name', 'email', 'phone_num',
            'job_title', 'department', 'photo', 'signature',
        ]

    def __init__(self, *args, **kwargs):
        readonly_fields = set(kwargs.pop("readonly_fields", ()))
        require_signature = kwargs.pop("require_signature", False)
        super().__init__(*args, **kwargs)
        self.require_signature = require_signature

        if require_signature and not self.instance.signature:
            self.fields["signature"].required = True
            self.fields["signature"].help_text = "Upload your signature. This is required before you can save your profile."

        for name, field in self.fields.items():
            if field.widget.__class__.__name__ == "CheckboxInput":
                field.widget.attrs.update({'class': 'form-check-input'})
            else:
                field.widget.attrs.update({'class': 'form-control'})

        for name in readonly_fields:
            if name not in self.fields:
                continue
            field = self.fields[name]
            field.disabled = True
            field.widget.attrs.update({
                "class": f"{field.widget.attrs.get('class', '')} bg-light text-muted".strip(),
                "aria-readonly": "true",
            })

    def clean_email(self):
        email = self.cleaned_data.get('email')

        if email:
            email = email.strip().lower()
            qs = Profile.objects.filter(email__iexact=email)

            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)

            if qs.exists():
                raise forms.ValidationError("This email is already in use.")

        return email

    def clean(self):
        cleaned = super().clean()
        if self.require_signature and not cleaned.get("signature") and not self.errors.get("signature"):
            self.add_error("signature", "A signature is required and cannot be removed.")

        return cleaned

    def get_groups(self):
        return {
            "Personal Information": ["first_name", "last_name", "email", "phone_num"],
            "Employment": ["job_title", "department"],
            "Documents": ["photo", "signature"],
        }


class LeaveForm(forms.ModelForm):
    class Meta:
        model = Leave
        fields = ["leave_type", "special_type", "start_date", "end_date", "reason"]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "end_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "reason": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "leave_type": forms.Select(attrs={"class": "form-control"}),
            "special_type": forms.Select(attrs={"class": "form-control"}),
        }

    def clean(self):
        cleaned = super().clean()
        s = cleaned.get("start_date")
        e = cleaned.get("end_date")
        leave_type = cleaned.get("leave_type")
        special_type = cleaned.get("special_type")
        reason = cleaned.get("reason")
        if s and e and e < s:
            raise forms.ValidationError("End date cannot be before start date.")

        if leave_type and leave_type.is_special:
            if not special_type:
                self.add_error("special_type", "Select special leave type")
            if not reason:
                self.add_error("reason", "Reason is required for special leave")
        else:
            cleaned["special_type"] = None
        return cleaned


class LeaveScheduleForm(forms.ModelForm):
    class Meta:
        model = LeaveSchedule
        fields = ["year", "leave_type", "start_date", "end_date", "notes"]
        widgets = {
            "year": forms.NumberInput(attrs={"class": "form-control", "min": 2020}),
            "leave_type": forms.Select(attrs={"class": "form-select"}),
            "start_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "end_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "notes": forms.Textarea(attrs={"rows": 3, "class": "form-control", "placeholder": "Optional note for HR"}),
        }



class AttendanceForm(forms.ModelForm):
    class Meta:
        model = Attendance
        fields = ['employee', 'status', 'latitude', 'longitude', 'address']
        widgets = {
            'latitude': forms.HiddenInput(),
            'longitude': forms.HiddenInput(),
            'address': forms.HiddenInput(),
            'employee': forms.Select(attrs={
                'class': 'form-control'
            }),
            'status': forms.Select(attrs={
                'class': 'form-control',
                'placeholder': 'Input message here.'
            }),
        }


class StaffAttendanceForm(forms.ModelForm):

    class Meta:
        model = Attendance
        fields = ['status', 'latitude', 'longitude', 'address']
        widgets = {
            'latitude': forms.HiddenInput(),
            'longitude': forms.HiddenInput(),
            'address': forms.HiddenInput(),
            'status': forms.Select(attrs={'class': 'form-control'}),
        }

    def clean_latitude(self):
        lat = self.cleaned_data.get("latitude")
        if lat is not None:
            return round(float(lat), 6)
        return lat

    def clean_longitude(self):
        lon = self.cleaned_data.get("longitude")
        if lon is not None:
            return round(float(lon), 6)
        return lon


# Training Form
class TrainingForm(forms.ModelForm):
    class Meta:
        model = Training
        fields = ['title', 'start_date', 'end_date', 'description', 'participants']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control', 'rows': '3',
                'placeholder': 'Input message here.'
            }),
            'start_date': forms.DateInput(attrs={
                'class': 'form-control', 'type': 'date'
            }),
            'end_date': forms.DateInput(attrs={
                'class': 'form-control', 'type': 'date'
            }),
            'participants': forms.CheckboxSelectMultiple(),


        }


class SituationReportForm(forms.ModelForm):
    class Meta:
        model = SituationReport
        fields = ["title", "description", "attachment"]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter situation title"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Describe the situation in detail..."}),
            "attachment": forms.FileInput(attrs={"class": "form-control"}),
        }


class UpdateSitrepStatusForm(forms.ModelForm):
    class Meta:
        model = SituationReport
        fields = ["status"]
        widgets = {
            "status": forms.Select(attrs={"class": "form-control"}),
        }



# class OrientationPlanCreateForm(forms.ModelForm):
#     departments = forms.ModelMultipleChoiceField(
#         queryset=Department.objects.order_by("name"),
#         required=True,
#         widget=forms.CheckboxSelectMultiple(),
#         help_text="Select departments that must orient the staff member.",
#     )
#
#     class Meta:
#         model = OrientationPlan
#         fields = ["notes"]
#         widgets = {
#             "notes": forms.Textarea(
#                 attrs={
#                     "class": "form-control",
#                     "rows": 3,
#                     "placeholder": "Optional HR notes for the orientation plan...",
#                 }
#             ),
#         }

class OrientationPlanCreateForm(forms.ModelForm):
    departments = forms.ModelMultipleChoiceField(
        queryset=Department.objects.order_by("name"),
        required=True,
        widget=forms.CheckboxSelectMultiple(
            attrs={"class": "oc-department-checkbox"}
        ),
        help_text="Select all departments that must orient the staff member.",
    )

    class Meta:
        model = OrientationPlan
        fields = ["notes"]
        widgets = {
            "notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Optional HR notes for the orientation plan...",
                }
            ),
        }


class OrientationSessionScheduleForm(forms.ModelForm):
    class Meta:
        model = OrientationSession
        fields = ["scheduled_start", "scheduled_end"]
        widgets = {
            "scheduled_start": forms.DateTimeInput(
                attrs={"type": "datetime-local", "class": "form-control"}
            ),
            "scheduled_end": forms.DateTimeInput(
                attrs={"type": "datetime-local", "class": "form-control"}
            ),
        }

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("scheduled_start")
        end = cleaned.get("scheduled_end")
        if start and end and end <= start:
            self.add_error("scheduled_end", "End time must be after start time.")
        return cleaned


class OrientationSessionCompleteForm(forms.ModelForm):
    class Meta:
        model = OrientationSession
        fields = ["completion_notes"]
        widgets = {
            "completion_notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Completion notes (optional)...",
                }
            ),
        }
