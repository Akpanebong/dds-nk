from django.contrib import admin

from .models import Leave, LeaveSchedule, Attendance, Training, LeaveDocument, SpecialLeaveType, LeaveType, SituationReport, StaffDevice
from .employee_models import BankDetail, Dependant, EducationHistory, EmergencyContact, EmployeeAddress, EmployeeContact, EmployeePersonalInfo, WorkExperience
from .orientation_models import OrientationPlan, OrientationSession


@admin.register(Leave)
class LeaveAdmin(admin.ModelAdmin):
    list_display = ("employee", "leave_type", "start_date", "end_date", "status")
    list_filter = ("leave_type", "status")


@admin.register(LeaveDocument)
class LeaveDocumentAdmin(admin.ModelAdmin):
    list_display = ("leave", "file", "created_at")


@admin.register(LeaveSchedule)
class LeaveScheduleAdmin(admin.ModelAdmin):
    list_display = ("employee", "year", "leave_type", "start_date", "end_date", "status")
    list_filter = ("year", "status", "leave_type")


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ("employee", "date", "status")
    list_filter = ("status",)


@admin.register(Training)
class TrainingAdmin(admin.ModelAdmin):
    list_display = ("title", "start_date", "end_date")


admin.site.register((SpecialLeaveType, LeaveType, SituationReport, StaffDevice))


@admin.register(OrientationPlan)
class OrientationPlanAdmin(admin.ModelAdmin):
    list_display = ("staff", "status", "created_at", "updated_at")


@admin.register(OrientationSession)
class OrientationSessionAdmin(admin.ModelAdmin):
    list_display = ("plan", "department", "status", "scheduled_start", "scheduled_end")
