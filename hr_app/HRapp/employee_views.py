from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from core.utils import stamp_audit

from .employee_forms import (
    AddressFormSet,
    BankForm,
    ContactFormSet,
    DependantFormSet,
    EducationFormSet,
    EmergencyFormSet,
    ExperienceFormSet,
    PersonalInfoForm,
    ProfileForm,
    StaffProfileCreateForm,
    EmployeeRecordForm,
)
from .employee_models import (
    BankDetail,
    Employee,
    EmployeePersonalInfo,
)
from .views import is_hr
from .orientation_models import OrientationPlanStatus
from .orientation_models import OrientationPlanStatus
from .orientation_models import OrientationPlanStatus


def _forms(user, data=None, files=None):
    employee, _ = Employee.objects.get_or_create(pk=user.pk)
    personal = EmployeePersonalInfo.objects.filter(employee=employee).first()
    bank = BankDetail.objects.filter(employee=employee).first()
    return {
        'profile_form': ProfileForm(data, files, instance=user, prefix='profile'),
        'personal_form': PersonalInfoForm(data, instance=personal, prefix='personal'),
        'bank_form': BankForm(data, instance=bank, prefix='bank'),
        'addresses': AddressFormSet(data, instance=employee, prefix='addresses'),
        'contacts': ContactFormSet(data, instance=employee, prefix='contacts'),
        'emergency': EmergencyFormSet(data, instance=employee, prefix='emergency'),
        'dependants': DependantFormSet(data, instance=employee, prefix='dependants'),
        'education': EducationFormSet(data, instance=employee, prefix='education'),
        'experience': ExperienceFormSet(data, instance=employee, prefix='experience'),
    }


def _profile_sections(forms):
    return [
        {'title': 'Personal information', 'form': forms['personal_form']},
        {'title': 'Addresses', 'formset': forms['addresses']},
        {'title': 'Contact channels', 'formset': forms['contacts']},
        {'title': 'Emergency contacts', 'formset': forms['emergency']},
        {'title': 'Dependants', 'formset': forms['dependants']},
        {'title': 'Education history', 'formset': forms['education']},
        {'title': 'Work experience', 'formset': forms['experience']},
        {'title': 'Banking details', 'form': forms['bank_form']},
    ]


@login_required
def profile_update(request):
    forms = _forms(request.user, request.POST or None, request.FILES or None)
    if request.method == 'POST':
        valid = all([form.is_valid() for form in forms.values()])
        confirmed = request.POST.get('confirm_update') == 'on'
        if not confirmed:
            messages.error(request, 'Please confirm that the information is accurate before saving.')
            valid = False
        if valid:
            with transaction.atomic():
                stamp_audit(forms['profile_form'].save(commit=False), request.user).save()
                personal = forms['personal_form'].save(commit=False)
                personal.employee = Employee.objects.get(pk=request.user.pk)
                stamp_audit(personal, request.user, creating=personal._state.adding).save()
                if forms['bank_form'].has_changed():
                    bank = forms['bank_form'].save(commit=False)
                    bank.employee = Employee.objects.get(pk=request.user.pk)
                    stamp_audit(bank, request.user, creating=bank._state.adding).save()
                for key in ('addresses', 'contacts', 'emergency', 'dependants', 'education', 'experience'):
                    for obj in forms[key].save(commit=False):
                        obj.employee = Employee.objects.get(pk=request.user.pk)
                        stamp_audit(obj, request.user, creating=obj._state.adding).save()
                    for obj in forms[key].deleted_objects:
                        obj.delete()
                    forms[key].save_m2m()
            messages.success(request, 'Your staff profile has been updated successfully.')
            return redirect('hr:profile')
    return render(request, 'staff/profile.html', {
        'forms': forms,
        'profile_form': forms['profile_form'],
        'profile_sections': _profile_sections(forms),
        'title': 'My employee profile',
    })


@login_required
def staff_create(request):
    """Create the StaffProfile first, then its supplemental employee record."""
    if not is_hr(request.user):
        messages.error(request, 'Access denied.')
        return redirect('hr:profile')

    profile_form = StaffProfileCreateForm(request.POST or None, request.FILES or None)
    employee_form = EmployeeRecordForm(request.POST or None)
    if request.method == 'POST' and profile_form.is_valid() and employee_form.is_valid():
        with transaction.atomic():
            profile = profile_form.save()
            employee = employee_form.save(commit=False)
            # Employee is now an alias for StaffProfile.  Do not save the
            # record form as a second profile; copy its HR fields onto the
            # profile that was just created.
            for field_name in employee_form.fields:
                setattr(profile, field_name, getattr(employee, field_name))
            profile.status = 'Probation'
            profile.save()
        messages.success(request, 'Staff profile created successfully.')
        return redirect('hr:employee_list')

    return render(request, 'hr/employee_profile.html', {
        'profile_form': profile_form,
        'employee_form': employee_form,
        'profile_sections': [],
        'title': 'Create staff profile',
        'is_create': True,
    })



@login_required
def staff_update(request, pk, slug):
    if not request.user.is_superuser and request.user.user_type == "VSLA":
        messages.error(request, 'Access denied.')
        return redirect('hr:employee_list')

    employee = get_object_or_404(Employee.objects, pk=pk, slug=slug)
    profile_form = ProfileForm(request.POST or None, request.FILES or None, instance=employee.user)
    employee_form = EmployeeRecordForm(request.POST or None, instance=employee)
    if request.method == 'POST' and profile_form.is_valid() and employee_form.is_valid():
        with transaction.atomic():
            profile_form.save()
            employee_form.save()
            if employee.staff_id != employee.user.staff_reg_no:
                employee.staff_id = employee.user.staff_reg_no
                employee.save(update_fields=['staff_reg_no'])
        messages.success(request, 'Staff profile updated successfully.')
        return redirect('hr:employee_list')

    return render(request, 'hr/employee_profile.html', {
        'profile_form': profile_form,
        'employee_form': employee_form,
        'profile_sections': [],
        'title': 'Update staff profile',
        'is_update': True,
        'employee': employee,
    })


@login_required(login_url='login')
def probation_confirm(request, pk, slug):
    """Move a probationary staff member to Active after orientation completion."""
    if not (is_hr(request.user) or request.user.is_superuser):
        messages.error(request, 'Only HR or the ED can confirm probation.')
        return redirect('hr:employee_list')

    staff = get_object_or_404(Employee, pk=pk, slug=slug)
    if staff.status != 'Probation':
        messages.info(request, 'This staff member is not currently on probation.')
        return redirect('hr:employee_list')

    plan = getattr(staff, 'orientation_plan', None)
    if not plan or plan.status != OrientationPlanStatus.COMPLETED:
        messages.error(request, 'Complete all orientation sessions before confirming probation.')
        return redirect('hr:orientation_hr_list')

    if request.method == 'POST':
        staff.status = 'Active'
        staff.save(update_fields=['status'])
        messages.success(request, f'{staff.get_full_name()} has been confirmed as Active staff.')
    return redirect('hr:orientation_hr_detail', plan_id=plan.id)
