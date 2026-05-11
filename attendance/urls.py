from django.contrib.auth.decorators import login_required
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
    # Temporary dev/testing clock-in — login only, no module permission required
    path('clock/', login_required(views.attendance_clock), name='attendance_clock'),
    # JSON endpoint for live polling — login only
    path('recent-json/', login_required(views.attendance_recent_json), name='attendance_recent_json'),
]
