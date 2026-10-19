from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import AuditLog, Department, StaffProfile

admin.site.site_header = 'DDS-NK THRIVE Administration'
admin.site.site_title = 'DDS-NK THRIVE Admin'
admin.site.index_title = 'Integrated Management System'


@admin.register(StaffProfile)
class StaffProfileAdmin(UserAdmin):
    list_display = (
        'staff_reg_no', 'username', 'email', 'job_title',
        'user_type', 'department', 'status', 'probation_end_date', 'is_active',
    )
    list_filter = ('user_type', 'department', 'status', 'is_active', 'is_staff', 'is_superuser')
    search_fields = ('staff_reg_no', 'username', 'email', 'first_name', 'last_name', 'phone_num')
    ordering = ('staff_reg_no',)
    readonly_fields = ('staff_reg_no', 'last_login', 'date_joined', 'last_seen')
    filter_horizontal = ('groups', 'user_permissions')
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Personal information', {'fields': ('first_name', 'last_name', 'email', 'phone_num', 'photo')}),
        ('Staff information', {'fields': ('staff_reg_no', 'user_type', 'job_title', 'category', 'department', 'supervised_by', 'status', 'probation_start_date', 'probation_end_date', 'last_seen', 'date_joined')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'email', 'first_name', 'last_name', 'password1', 'password2'),
        }),
    )


@admin.register(AuditLog)
class AuditAdmin(admin.ModelAdmin):
    list_display=('created_at','actor','module','action','object_type','object_id')
    list_filter=('module','action','created_at')
    search_fields=('actor__username','detail','object_id')
    readonly_fields=('created_at',)


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ('name', 'key', 'head')
    list_filter = ('key',)
    search_fields = ('name', 'key', 'head__username', 'head__email')
