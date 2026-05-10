from django.urls import path
from accounts.access import module_access_required

from . import views

app_name = 'attendance'
attendance_access = module_access_required('can_manage_attendance')

urlpatterns = [
    path('', attendance_access(views.attendance_list), name='attendance_list'),
    path('add/', attendance_access(views.attendance_add), name='attendance_add'),
    path('<int:pk>/edit/', attendance_access(views.attendance_edit), name='attendance_edit'),
    path('<int:pk>/delete/', attendance_access(views.attendance_delete), name='attendance_delete'),
]
