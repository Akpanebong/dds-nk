from django.urls import path

from . import views

app_name = 'notifications'

urlpatterns = [
    path('<int:pk>/', views.open_notification, name='open'),
    path('mark-all-read/', views.mark_all_read, name='mark_all_read'),
]
