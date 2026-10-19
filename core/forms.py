from django import forms
from django.contrib.auth.forms import AuthenticationForm

from .models import StaffProfile


class StaffAuthenticationForm(AuthenticationForm):
    username = forms.CharField(
        label='Username, email, staff registration number, or phone',
        widget=forms.TextInput(attrs={'autocomplete': 'username'}),
    )


class AccountSettingsForm(forms.ModelForm):
    class Meta:
        model = StaffProfile
        fields = ['username', 'email', 'first_name', 'last_name', 'phone_num']
