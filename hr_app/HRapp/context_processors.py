from .models import Leave


def event_profile(request):

    leave = Leave.objects.filter(status="Pending").order_by('applied_date')

    return {'leaves': leave}
