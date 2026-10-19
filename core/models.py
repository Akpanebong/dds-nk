from uuid import uuid4

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.conf import settings
from django.db import models
from django.utils import timezone

from .model_audit_stamp import AuditStampedModel
from .slug import unique_slug


class StaffProfileManager(BaseUserManager):
    @staticmethod
    def _compat_kwargs(kwargs):
        converted = {}
        for key, value in kwargs.items():
            if key == 'user':
                converted['pk'] = getattr(value, 'pk', value)
            elif key.startswith('user__'):
                converted[key[6:]] = value
            else:
                converted[key] = value
        return converted

    def filter(self, *args, **kwargs):
        return super().filter(*args, **self._compat_kwargs(kwargs))

    def get(self, *args, **kwargs):
        return super().get(*args, **self._compat_kwargs(kwargs))

    def get_or_create(self, defaults=None, **kwargs):
        return super().get_or_create(defaults=defaults, **self._compat_kwargs(kwargs))

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('An email address is required.')
        user = self.model(email=self.normalize_email(email), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')
        return self.create_user(email, password, **extra_fields)


class Department(AuditStampedModel):
    key = models.SlugField(max_length=30, unique=True)
    name = models.CharField(max_length=120, unique=True)
    head = models.OneToOneField(
        'StaffProfile',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='headed_department',
    )

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class StaffProfile(AuditStampedModel, AbstractBaseUser, PermissionsMixin):
    STATUS_CHOICES = (
        ('Probation', 'Probation'),
        ('Active', 'Active'),
        ('On Leave', 'On Leave'),
        ('Exit', 'Exit'),
    )

    class UserType(models.TextChoices):
        STAFF = 'Staff', 'Staff'
        VOLUNTEER = 'Volunteer', 'Volunteer'
        INTERN = 'Intern', 'Intern'
        VSLA = 'VSLA', 'VSLA'

    slug = models.SlugField(max_length=255, unique=True)
    username = models.CharField(max_length=150, unique=True, blank=True)
    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    staff_reg_no = models.CharField(max_length=30, unique=True, blank=True)
    phone_num = models.CharField(max_length=40, unique=True, null=True, blank=True)
    job_title = models.CharField(max_length=150, blank=True)
    category = models.CharField(max_length=100, blank=True)
    department = models.ForeignKey(Department, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='staff',)
    supervised_by = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='supervised_staff',
    )
    photo = models.ImageField(upload_to='staff/', blank=True, null=True)
    signature = models.FileField(upload_to='staff/signatures/', blank=True, null=True, help_text='Upload a clear .png image of your staff signature.',)
    user_type = models.CharField(max_length=20, choices=UserType.choices, default=UserType.STAFF)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Probation')
    probation_start_date = models.DateField(null=True, blank=True)
    probation_end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    last_seen = models.DateTimeField(blank=True, null=True)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = StaffProfileManager()

    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = ['email']

    class Meta:
        verbose_name = 'staff profile'
        verbose_name_plural = 'staff profiles'

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        pending_username = not self.username
        generated_staff_reg_no = is_new and not self.staff_reg_no
        if pending_username:
            self.username = f'pending-{uuid4().hex}'
        if generated_staff_reg_no:
            # staff_reg_no is unique, so never insert a blank value while
            # waiting for the primary key needed by the final format.
            current_year = timezone.localdate().year % 100
            self.staff_reg_no = f'DDS-{current_year:02d}-TMP-{uuid4().hex[:10].upper()}'
        if not self.slug:
            self.slug = unique_slug(self, self.username)
        super().save(*args, **kwargs)
        if is_new and (generated_staff_reg_no or pending_username):
            current_year = timezone.localdate().year % 100
            if generated_staff_reg_no:
                self.staff_reg_no = f'DDS-{current_year:02d}-{self.pk:06d}'
            if pending_username:
                self.username = f'staff-{self.pk:06d}'
            if self.slug.startswith('pending-'):
                self.slug = unique_slug(self, self.username)
            super().save(using=kwargs.get('using'), update_fields=['staff_reg_no', 'username', 'slug'])

    def clean(self):
        from django.core.exceptions import ValidationError

        super().clean()
        if self.status == 'Probation':
            if not self.probation_start_date or not self.probation_end_date:
                raise ValidationError({
                    'probation_start_date': 'Probation start date is required.',
                    'probation_end_date': 'Probation end date is required.',
                })
        if self.probation_start_date and self.probation_end_date:
            if self.probation_end_date < self.probation_start_date:
                raise ValidationError({'probation_end_date': 'Probation end date must be on or after the start date.'})

    def get_full_name(self):
        return f'{self.first_name} {self.last_name}'.strip() or self.username

    def get_short_name(self):
        return self.first_name or self.username

    @property
    def employee(self):
        return self

    @property
    def user(self):
        return self

    @user.setter
    def user(self, value):
        # Legacy HR code assigned the linked profile here; the profile is now self.
        return None

    @property
    def user_id(self):
        return self.pk

    @property
    def staff_id(self):
        return self.staff_reg_no

    @staff_id.setter
    def staff_id(self, value):
        self.staff_reg_no = value

    def email_user(self, subject, message, from_email=None, **kwargs):
        from django.core.mail import send_mail
        send_mail(subject, message, from_email, [self.email], **kwargs)

    def __str__(self):
        return self.get_full_name()


class AuditLog(AuditStampedModel):
    slug = models.SlugField(max_length=255, unique=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=100)
    module = models.CharField(max_length=60)
    object_type = models.CharField(max_length=120, blank=True)
    object_id = models.CharField(max_length=60, blank=True)
    detail = models.TextField(blank=True)
    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(self, f'{self.module}-{self.action}-{self.object_id}')
        super().save(*args, **kwargs)

    class Meta:
        ordering = ['-created_at']
