from django.contrib import admin
from .models import Appraisal, PerformanceImprovementPlan


@admin.register(Appraisal)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ('employee', 'supervisor', 'year')


admin.site.register( PerformanceImprovementPlan)