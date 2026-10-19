from django.contrib.auth import get_user_model
from django.db.models import Q


class StaffProfileBackend:
    """Authenticate staff using username, email, registration number, or phone."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        identifier = username or kwargs.get('email') or kwargs.get('staff_reg_no') or kwargs.get('phone_num')
        if not identifier or password is None:
            return None
        user_model = get_user_model()
        try:
            user = user_model.objects.get(
                Q(username__iexact=identifier)
                | Q(email__iexact=identifier)
                | Q(staff_reg_no__iexact=identifier)
                | Q(phone_num=identifier)
            )
        except user_model.DoesNotExist:
            return None
        if user.check_password(password) and user.is_active:
            return user
        return None

    def get_user(self, user_id):
        user_model = get_user_model()
        try:
            return user_model.objects.get(pk=user_id)
        except user_model.DoesNotExist:
            return None
