from django.contrib import admin
from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('recipient', 'title', 'level', 'read_at', 'created_at')
    list_filter = ('level', 'read_at')
    search_fields = ('recipient__email', 'recipient__first_name', 'recipient__last_name', 'title', 'message')
