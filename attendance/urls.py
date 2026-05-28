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

    # Work Schedules
    path('schedules/', attendance_access(views.schedule_list), name='schedule_list'),
    path('schedules/add/', attendance_access(views.schedule_add), name='schedule_add'),
    path('schedules/<int:pk>/edit/', attendance_access(views.schedule_edit), name='schedule_edit'),
    path('schedules/<int:pk>/delete/', attendance_access(views.schedule_delete), name='schedule_delete'),

    # Temporary dev/testing clock-in — login only, no module permission required
    path('clock/', login_required(views.attendance_clock), name='attendance_clock'),
    # JSON endpoint for live polling — login only
    path('recent-json/', login_required(views.attendance_recent_json), name='attendance_recent_json'),

    # Attendance Locations (admin/HR only — module permission required)
    path('locations/', attendance_access(views.location_list), name='location_list'),
    path('locations/add/', attendance_access(views.location_add), name='location_add'),
    path('locations/<int:pk>/edit/', attendance_access(views.location_edit), name='location_edit'),
    path('locations/<int:pk>/delete/', attendance_access(views.location_delete), name='location_delete'),

    # Shift Templates (admin/HR only)
    path('shifts/', attendance_access(views.shift_list), name='shift_list'),
    path('shifts/add/', attendance_access(views.shift_add), name='shift_add'),
    path('shifts/<int:pk>/edit/', attendance_access(views.shift_edit), name='shift_edit'),
    path('shifts/<int:pk>/delete/', attendance_access(views.shift_delete), name='shift_delete'),

    # Employee Daily Schedules (admin/HR only)
    path('employee-schedules/', attendance_access(views.employee_schedule_list), name='employee_schedule_list'),
    path('employee-schedules/add/', attendance_access(views.employee_schedule_add), name='employee_schedule_add'),
    path('employee-schedules/bulk/', attendance_access(views.employee_schedule_bulk), name='employee_schedule_bulk'),
    path('employee-schedules/<int:pk>/edit/', attendance_access(views.employee_schedule_edit), name='employee_schedule_edit'),
    path('employee-schedules/<int:pk>/delete/', attendance_access(views.employee_schedule_delete), name='employee_schedule_delete'),

    # Employee WiFi/IP Portal — login only, no module permission (employee self-service)
    path('portal/', login_required(views.attendance_portal), name='attendance_portal'),
]
