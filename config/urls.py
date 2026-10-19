from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views
from django.urls import reverse_lazy
from core import views as core_views
from core.forms import StaffAuthenticationForm
urlpatterns = [
    path('admin/', admin.site.urls),
    path('', core_views.home, name='home'),
    path('accounts/login/', auth_views.LoginView.as_view(
        template_name='core/login.html',
        authentication_form=StaffAuthenticationForm,
    ), name='login'),
    path('accounts/logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('accounts/password-change/', auth_views.PasswordChangeView.as_view(
        template_name='core/password_change_form.html',
        success_url=reverse_lazy('password_change_done'),
    ), name='password_change'),
    path('accounts/password-change/done/', auth_views.PasswordChangeDoneView.as_view(
        template_name='core/password_change_done.html',
    ), name='password_change_done'),
    path('accounts/profile/', core_views.account_settings, name='account_settings'),
    path('accounts/password-reset/', auth_views.PasswordResetView.as_view(
        template_name='core/password_reset_form.html',
        email_template_name='core/password_reset_email.txt',
        subject_template_name='core/password_reset_subject.txt',
        success_url=reverse_lazy('password_reset_done'),
    ), name='password_reset'),
    path('accounts/password-reset/done/', auth_views.PasswordResetDoneView.as_view(
        template_name='core/password_reset_done.html',
    ), name='password_reset_done'),
    path('accounts/reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='core/password_reset_confirm.html',
        success_url=reverse_lazy('password_reset_complete'),
    ), name='password_reset_confirm'),
    path('accounts/reset/complete/', auth_views.PasswordResetCompleteView.as_view(
        template_name='core/password_reset_complete.html',
    ), name='password_reset_complete'),
    path('portal/', core_views.portal, name='portal'),
    path('meal/', include('meal_app.meal.urls')),
    path('procurement/', include('procure_app.procurement.urls')),
    path('hr/', include('hr_app.HRapp.urls')),
    path('hr/', include('hr_app.appraisals.urls')),
    path('notifications/', include('notifications.urls')),
    path('vsla/', include('vsla_app.vsla.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
