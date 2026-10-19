from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.contrib import messages

from .forms import AccountSettingsForm

def home(request):
    return redirect('portal') if request.user.is_authenticated else redirect('login')
@login_required
def portal(request):
    return render(request,'core/portal.html')


@login_required
def account_settings(request):
    form = AccountSettingsForm(request.POST or None, instance=request.user)
    if form.is_valid():
        form.save()
        messages.success(request, 'Your account details were updated.')
        return redirect('account_settings')
    return render(request, 'core/account_settings.html', {'form': form})
