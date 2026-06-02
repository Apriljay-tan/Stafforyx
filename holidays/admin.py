from django.contrib import admin

from .models import CompanyHolidayPolicy, Holiday, HolidayException


@admin.register(Holiday)
class HolidayAdmin(admin.ModelAdmin):
    list_display = ("name", "date", "holiday_type", "company", "is_enabled", "is_paid")
    list_filter = ("holiday_type", "is_enabled", "is_paid", "company")
    search_fields = ("name",)


@admin.register(HolidayException)
class HolidayExceptionAdmin(admin.ModelAdmin):
    list_display = ("holiday", "department", "employee", "not_observed")


@admin.register(CompanyHolidayPolicy)
class CompanyHolidayPolicyAdmin(admin.ModelAdmin):
    list_display = ("company",)
