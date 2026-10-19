from django.urls import path
from . import views

app_name = 'meal'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('iptt/', views.iptt, name='iptt'),
    path('output-dashboard/', views.output_dashboard, name='output_dashboard'),
    path('finance/', views.finance_dashboard, name='finance'),
    path('fy26-output/', views.fy26_output_dashboard, name='fy26_output'),
    path('exports/activity-tracker.xlsx', views.tracker_export, name='tracker_export'),
    path('activities/', views.activity_list, name='activities'),
    path('activities/new/', views.activity_create, name='activity_create'),
    path('activities/<int:pk>/edit/', views.activity_update, name='activity_update'),
    path('activities/<int:pk>/delete/', views.activity_delete, name='activity_delete'),
    path('activities/<int:pk>/capture/', views.activity_capture, name='activity_capture'),
    path('records/', views.records, name='records'),
    path('records/<int:pk>/edit/', views.record_update, name='record_update'),
    path('records/<int:pk>/review/', views.review_record, name='review_record'),
    path('hierarchy/', views.hierarchy_list, name='hierarchy'),
    path('objectives/', views.objective_list, name='objective_list'),
    path('outputs/', views.output_list, name='output_list'),
    path('quarter-plans/', views.quarterplan_list, name='quarterplan_list'),
    path('quarter-plans/new/', views.quarterplan_create, name='quarterplan_create'),
    path('quarter-plans/<int:pk>/edit/', views.quarterplan_update, name='quarterplan_update'),
    path('quarter-plans/<int:pk>/delete/', views.quarterplan_delete, name='quarterplan_delete'),
    path('framework/<str:kind>/new/', views.framework_create, name='framework_create'),
    path('framework/<str:kind>/<slug:code>/', views.framework_detail, name='framework_detail'),
    path('framework/<str:kind>/<slug:code>/edit/', views.framework_update, name='framework_update'),
    path('framework/<str:kind>/<slug:code>/delete/', views.framework_delete, name='framework_delete'),
    path('ajax/objectives/<slug:code>/outputs/', views.ajax_outputs, name='ajax_outputs'),
    path('ajax/outputs/<slug:code>/activities/', views.ajax_indicators, name='ajax_indicators'),
]
