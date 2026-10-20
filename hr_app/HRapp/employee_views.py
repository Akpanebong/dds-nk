from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
import logging
import secrets
import string
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


logger = logging.getLogger(__name__)


def _generate_staff_password(length=16):
    alphabet = string.ascii_letters + string.digits + '!@#$%^&*_-+'
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def _send_staff_welcome_email(*, request, profile, initial_password):
    """Send the new staff member their first-login credentials."""
    login_url = request.build_absolute_uri(reverse('login'))
    full_name = profile.get_full_name() or profile.username
    message = (
        f"Dear {full_name},\n\n"
        "Your DDS-NK THRIVE staff account has been created.\n\n"
        f"Username: {profile.username}\n"
        f"Staff registration number: {profile.staff_reg_no}\n"
        f"Temporary password: {initial_password}\n\n"
        f"Sign in here: {login_url}\n\n"
        "Please sign in and change your username and password immediately. "
        "Your staff registration number is permanent and cannot be changed.\n\n"
        "If you did not expect this account, please contact HR."
    )
    try:
        send_mail(
            subject='Your DDS-NK THRIVE staff account',
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[profile.email],
            fail_silently=False,
        )
    except Exception as exc:
        # Do not undo a successfully created account because an SMTP server
        # is temporarily unavailable.  Keep the failure visible to HR and in
        # the application logs so the credentials can be resent safely.
        logger.exception('Unable to send welcome email to %s', profile.email)
        messages.warning(
            request,
            'Staff account created, but the welcome email could not be sent. '
            f'Email error: {exc}. Please verify the recipient address and email settings.',
        )


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
    """Create a staff profile and copy its supplemental HR fields."""
    if not is_hr(request.user):
        messages.error(request, "Access denied.")
        return redirect("hr:profile")

    profile_form = StaffProfileCreateForm(
        request.POST or None,
        request.FILES or None,
    )
    employee_form = EmployeeRecordForm(request.POST or None)

    if request.method == "POST":
        profile_valid = profile_form.is_valid()
        employee_valid = employee_form.is_valid()

        if profile_valid and employee_valid:
            with transaction.atomic():
                initial_password = _generate_staff_password()
                profile = profile_form.save(commit=False)
                profile.set_password(initial_password)
                profile.save()
                employee_data = employee_form.save(commit=False)

                # Copy supplemental HR fields to the new staff profile.
                for field_name in employee_form.fields:
                    if hasattr(profile, field_name):
                        setattr(
                            profile,
                            field_name,
                            getattr(employee_data, field_name),
                        )

                profile.status = "Probation"
                profile.save()
                transaction.on_commit(
                    lambda: _send_staff_welcome_email(
                        request=request,
                        profile=profile,
                        initial_password=initial_password,
                    )
                )

            messages.success(
                request,
                "Staff profile created successfully.",
            )
            return redirect("hr:employee_list")

    return render(
        request,
        "hr/employee_profile.html",
        {
            "profile_form": profile_form,
            "employee_form": employee_form,
            "profile_sections": [],
            "title": "Create staff profile",
            "is_create": True,
        },
    )


@login_required
def staff_update(request, pk, slug):
    """Update a staff profile and its supplemental HR information."""
    if (
        not request.user.is_superuser
        and request.user.user_type == "VSLA"
    ):
        messages.error(request, "Access denied.")
        return redirect("hr:employee_list")

    # Employee is a compatibility alias for StaffProfile.  There is no
    # separate ``user`` relation after the custom-user migration.
    employee = get_object_or_404(Employee.objects.select_related("department"), pk=pk, slug=slug)

    profile_form = ProfileForm(
        request.POST or None,
        request.FILES or None,
        instance=employee,
    )
    employee_form = EmployeeRecordForm(
        request.POST or None,
        instance=employee,
    )

    if request.method == "POST":
        profile_valid = profile_form.is_valid()
        employee_valid = employee_form.is_valid()

        if profile_valid and employee_valid:
            with transaction.atomic():
                profile = profile_form.save()
                employee_record = employee_form.save(commit=False)

                # Keep the employee record aligned with the profile.
                employee_record.save()

            messages.success(
                request,
                "Staff profile updated successfully.",
            )
            return redirect("hr:employee_list")

    return render(
        request,
        "hr/employee_profile.html",
        {
            "profile_form": profile_form,
            "employee_form": employee_form,
            "profile_sections": [],
            "title": "Update staff profile",
            "is_update": True,
            "employee": employee,
        },
    )

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
