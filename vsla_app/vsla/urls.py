from django.urls import path
from . import views

app_name = "vsla"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("groups/", views.group_list, name="groups"),
    path("groups/new/", views.group_create, name="group_create"),
    path("groups/<slug:slug>/", views.group_detail, name="group_detail"),
    path("members/", views.member_list, name="members"),
    path("members/new/", views.member_create, name="member_create"),
    path("members/<slug:member_no>/", views.member_detail, name="member_detail"),
    path("savings/", views.savings_list, name="savings"),
    path("savings/new/", views.savings_create, name="savings_create"),
    path("loans/", views.loan_list, name="loans"),
    path("loans/new/", views.loan_create, name="loan_create"),
    path("loans/<slug:loan_no>/", views.loan_detail, name="loan_detail"),
    path("loans/<slug:loan_no>/submit/", views.loan_submit, name="loan_submit"),
    path("loans/<slug:loan_no>/decision/", views.loan_decision, name="loan_decision"),
    path("loans/<slug:loan_no>/repay/", views.repayment_create, name="repayment_create"),
    path("meetings/", views.meeting_list, name="meetings"),
    path("meetings/new/", views.meeting_create, name="meeting_create"),
    path("social-fund/", views.social_fund_list, name="social_fund"),
    path("social-fund/new/", views.social_fund_create, name="social_fund_create"),
]
