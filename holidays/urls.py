from django.urls import path

from . import views

app_name = "holidays"

urlpatterns = [
    path("", views.holiday_list, name="holiday_list"),
    path("add/", views.holiday_add, name="holiday_add"),
    path("policy/", views.policy_edit, name="policy_edit"),
    path("<int:pk>/", views.holiday_detail, name="holiday_detail"),
    path("<int:pk>/edit/", views.holiday_edit, name="holiday_edit"),
    path("<int:pk>/toggle/", views.holiday_toggle, name="holiday_toggle"),
    path("<int:pk>/delete/", views.holiday_delete, name="holiday_delete"),
    path("<int:pk>/exceptions/add/", views.exception_add, name="exception_add"),
    path("exceptions/<int:pk>/delete/", views.exception_delete, name="exception_delete"),
]
