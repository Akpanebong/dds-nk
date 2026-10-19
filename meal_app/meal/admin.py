from django.contrib import admin
from .models import ActivityRecord, Indicator, Output, StrategicObjective


@admin.register(StrategicObjective)
class StrategicObjectiveAdmin(admin.ModelAdmin):
    list_display = ('code', 'title')
    search_fields = ('code', 'title')


@admin.register(Output)
class OutputAdmin(admin.ModelAdmin):
    list_display = ('code', 'title', 'objective')
    list_filter = ('objective',)
    search_fields = ('code', 'title')


@admin.register(Indicator)
class IndicatorAdmin(admin.ModelAdmin):
    list_display = ('code', 'title', 'activity_type', 'output', 'reporting_frequency', 'target', 'active')
    list_filter = ('activity_type', 'reporting_frequency', 'active', 'output__objective')
    search_fields = ('code', 'title', 'indicator_text')


@admin.register(ActivityRecord)
class ActivityRecordAdmin(admin.ModelAdmin):
    list_display = ('activity', 'reporting_year', 'reporting_month', 'status', 'submitted_by', 'created_at')
    list_filter = ('status', 'reporting_year', 'reporting_month', 'indicator__activity_type')
    search_fields = ('indicator__code', 'indicator__title', 'comments')
