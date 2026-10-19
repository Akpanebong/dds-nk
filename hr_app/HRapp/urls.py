from django.urls import path
from . import views
from . import orientation_view as orient
from . import employee_views
from hr_app.appraisals.views import appraisal_list

app_name = 'hr'


urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('employees/', views.employee_list, name='employee_list'),
    path('staff/', views.employee_list, name='staff'),
    path('employees/add/', employee_views.staff_create, name='add_employee'),
    path('reviews/', appraisal_list, name='reviews'),
    path('employees/edit/<int:pk>/<slug:slug>/', employee_views.staff_update, name='edit_employee'),
    path('employees/<int:pk>/<slug:slug>/confirm-probation/', employee_views.probation_confirm, name='confirm_probation'),
    path('employees/delete/<int:pk>/<slug:slug>/', views.delete_employee, name='delete_employee'),
    path('profile/', employee_views.profile_update, name='profile'),
    path('leaves/', views.leave_list, name='leave_list'),
    path('leaves/supervisor/', views.supervisor_leave_list, name='supervisor_leave_list'),
    path('leaves/apply/', views.apply_leave, name='apply_leave'),
    path('leaves/schedule/', views.schedule_leave, name='schedule_leave'),
    path('leave/delete/<slug:slug>/', views.delete_leave, name='delete_leave'),

    path("leave/report/", views.leave_yearly_report, name="leave_report"),
    path("leave/report/pdf/", views.leave_yearly_report_pdf, name="leave_report_pdf"),
    path("leave/report/excel/", views.export_leave_report_excel, name="leave_report_excel"),
    path("leave/report/staff/excel/", views.export_leave_staff_excel, name="leave_staff_excel"),

    path("leave/<slug:slug>/", views.leave_detail, name="leave_detail"),
    path("apply/", views.apply_leave, name="apply_leave"),
    path("leave/<slug:slug>/approve/supervisor/<str:action>/", views.approve_supervisor, name="approve_supervisor"),
    path("leave/<slug:slug>/approve/hr/<str:action>/", views.approve_hr, name="approve_hr"),
    path("leave/<slug:slug>/approve/ed/<str:action>/", views.approve_ed, name="approve_ed"),


    # Attendance
    path('attendance/', views.attendance_list, name='attendance_list'),
    path('attendance/mark/', views.mark_attendance, name='mark_attendance'),
    path("attendance/export-pdf/", views.export_attendance_pdf, name="export_attendance_pdf"),
    path("attendance/export-excel/", views.export_attendance_excel, name="export_attendance_excel"),
    path("staff/attendance/mark/", views.staff_mark_attendance, name="staff_mark_attendance"),

    # Training
    path('training/', views.training_list, name='training_list'),
    path("training/<slug:slug>/detail/", views.TrainingDetailModalView.as_view(), name="training_detail_modal"),
    path('training/add/', views.add_training, name='add_training'),
    path("training/<slug:slug>/edit/", views.TrainingUpdateView.as_view(), name="training_edit"),
    path("training/<slug:slug>/trash/", views.trash_training, name="trash_training"),

    # Situation Report
    path("sitrep/", views.sitrep_list, name="sitrep_list"),
    path("sitrep/new/", views.create_sitrep, name="create_sitrep"),
    path("sitrep/<int:pk>/", views.sitrep_detail, name="sitrep_detail"),

        # Orientation (Probation)
    path("orientation/hr/", orient.orientation_hr_list, name="orientation_hr_list"),
    path("orientation/hr/<slug:staff_slug>/create/", orient.orientation_hr_create, name="orientation_hr_create"),
    path("orientation/hr/plan/<int:plan_id>/", orient.orientation_hr_detail, name="orientation_hr_detail"),

    path("orientation/cmt/", orient.orientation_cmt_list, name="orientation_cmt_list"),
    path("orientation/cmt/plan/<int:plan_id>/", orient.orientation_cmt_detail, name="orientation_cmt_detail"),

    path("orientation/head/", orient.orientation_head_list, name="orientation_head_list"),
    path("orientation/head/session/<int:session_id>/schedule/", orient.orientation_head_session_schedule, name="orientation_head_session_schedule"),
    path("orientation/head/session/<int:session_id>/complete/", orient.orientation_head_session_complete, name="orientation_head_session_complete"),

    path("orientation/my/", orient.orientation_my, name="orientation_my"),
]
