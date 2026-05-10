from django.urls import path

from . import views

app_name = 'reports'

urlpatterns = [
    path('', views.reports_dashboard, name='reports_dashboard'),
    path('employees/', views.employee_report, name='employee_report'),
    path('employees/export/', views.employee_report_export, name='employee_report_export'),
    path('attendance/', views.attendance_report, name='attendance_report'),
    path('attendance/export/', views.attendance_report_export, name='attendance_report_export'),
    path('leaves/', views.leave_report, name='leave_report'),
    path('leaves/export/', views.leave_report_export, name='leave_report_export'),
    path('payroll/', views.payroll_report, name='payroll_report'),
    path('payroll/export/', views.payroll_report_export, name='payroll_report_export'),
    path('documents/', views.documents_report, name='documents_report'),
    path('documents/export/', views.documents_report_export, name='documents_report_export'),
]
