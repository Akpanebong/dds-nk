from django.db import models

from core.models import StaffProfile

Profile = StaffProfile
# Compatibility import for the transition; Employee is no longer a database model.
Employee = StaffProfile

SEX_CHOICES = (("Male", "Male"), ("Female", "Female"), ("Other", "Other"), ("Prefer not to say", "Prefer not to say"))


class EmployeePersonalInfo(models.Model):
    employee = models.OneToOneField(StaffProfile, on_delete=models.CASCADE)
    marital_status = models.CharField(max_length=80, blank=True)
    sex = models.CharField(max_length=40, choices=SEX_CHOICES, blank=True)
    ethnicity = models.CharField(max_length=100, blank=True)
    blood_group = models.CharField(max_length=20, blank=True)
    date_of_birth = models.DateField(null=True)
    age = models.PositiveSmallIntegerField(null=True)
    national_id_no = models.CharField(max_length=100, blank=True)
    passport_no = models.CharField(max_length=100, blank=True)
    work_permit_no = models.CharField(max_length=100, blank=True)


class EmployeeAddress(models.Model):
    ADDRESS_TYPES = (("PERMANENT", "Permanent"), ("PRESENT", "Present"), ("OFFICE", "Office"))
    employee = models.ForeignKey(StaffProfile, on_delete=models.CASCADE)
    type = models.CharField(max_length=20, choices=ADDRESS_TYPES)
    country = models.CharField(max_length=100)
    city = models.CharField(max_length=100)
    district = models.CharField(max_length=100)
    address = models.TextField()
    postal_code = models.CharField(max_length=20, blank=True)


class EmployeeContact(models.Model):
    CONTACT_TYPES = (("PERSONAL", "Personal"), ("OFFICIAL", "Official"), ("HOME", "Home"))
    employee = models.ForeignKey(StaffProfile, on_delete=models.CASCADE)
    type = models.CharField(max_length=20, choices=CONTACT_TYPES)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)


class EmergencyContact(models.Model):
    employee = models.ForeignKey(StaffProfile, on_delete=models.CASCADE)
    name = models.CharField(max_length=200)
    relationship = models.CharField(max_length=100)
    phone = models.CharField(max_length=30)
    address = models.TextField(blank=True)


class Dependant(models.Model):
    employee = models.ForeignKey(StaffProfile, on_delete=models.CASCADE)
    name = models.CharField(max_length=200)
    relationship = models.CharField(max_length=100)
    date_of_birth = models.DateField(null=True)


class EducationHistory(models.Model):
    employee = models.ForeignKey(StaffProfile, on_delete=models.CASCADE)
    institution = models.CharField(max_length=255)
    qualification = models.CharField(max_length=255)
    year_graduated = models.IntegerField(null=True)
    certifications = models.TextField(blank=True)


class WorkExperience(models.Model):
    employee = models.ForeignKey(StaffProfile, on_delete=models.CASCADE)
    company = models.CharField(max_length=255)
    position = models.CharField(max_length=255)
    years = models.IntegerField(default=2020)
    skills = models.TextField(blank=True)


class BankDetail(models.Model):
    employee = models.OneToOneField(StaffProfile, on_delete=models.CASCADE)
    bank_name = models.CharField(max_length=150)
    branch = models.CharField(max_length=150)
    account_name = models.CharField(max_length=200)
    account_number = models.CharField(max_length=100)
    swift_code = models.CharField(max_length=80)
