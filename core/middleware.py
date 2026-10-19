from django.utils import timezone
from django.contrib.auth import get_user_model
from django.shortcuts import redirect


class LastSeenMiddleware:
    def __init__(self,get_response): self.get_response=get_response
    def __call__(self,request):
        response=self.get_response(request)
        if request.user.is_authenticated:
            if not request.session.get('_seen_update'):
                get_user_model().objects.filter(pk=request.user.pk).update(last_seen=timezone.now())
                request.session['_seen_update']=True
        return response


class UserTypeModuleMiddleware:
    """Keep VSLA-only accounts inside the VSLA workspace."""
    blocked_prefixes = ('/hr/', '/meal/', '/procurement/')

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (request.user.is_authenticated
                and getattr(request.user, 'user_type', 'Staff') == 'VSLA'
                and request.path.startswith(self.blocked_prefixes)):
            return redirect('portal')
        return self.get_response(request)
