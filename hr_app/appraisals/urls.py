from django.urls import path
from . import views

urlpatterns = [
    path('appraisals/', views.appraisal_list, name='appraisal_list'),
    path('appraisals/dashboard/', views.appraisal_dashboard, name='appraisal_dashboard'),
    path('appraisal/create/<slug:employee_slug>/', views.create_appraisal, name='create_appraisal'),
    path('appraisal/<slug:slug>/', views.appraisal_detail, name='appraisal_detail'),
    path('appraisal/<slug:slug>/download/', views.download_final_appraisal, name='download_final_appraisal'),
    path('appraisal/<slug:slug>/employee/', views.employee_submit, name='employee_submit'),
    path('appraisal/<slug:slug>/supervisor/', views.supervisor_review, name='supervisor_review'),
    path('appraisal/<slug:slug>/hr/', views.hr_review, name='hr_review'),
    path('appraisal/<slug:slug>/cmt/', views.cmt_approval, name='cmt_approval'),
    path("appraisal/<slug:slug>/send-pip/", views.send_pip, name="send_pip",),
    path("pip/<uuid:token>/", views.fill_pip, name="fill_pip",)
]
