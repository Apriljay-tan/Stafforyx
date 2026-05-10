from django.urls import path
from accounts.access import module_access_required

from . import views

app_name = 'reports'
reports_access = module_access_required('can_view_reports')
export_access = module_access_required('can_export_data')

urlpatterns = [
    path('', reports_access(views.reports_dashboard), name='reports_dashboard'),
    path('export-all/', export_access(views.export_all_data), name='export_all_data'),
    path('employees/', reports_access(views.employee_report), name='employee_report'),
    path('employees/export/', export_access(views.employee_report_export), name='employee_report_export'),
    path('attendance/', reports_access(views.attendance_report), name='attendance_report'),
    path('attendance/export/', export_access(views.attendance_report_export), name='attendance_report_export'),
    path('leaves/', reports_access(views.leave_report), name='leave_report'),
    path('leaves/export/', export_access(views.leave_report_export), name='leave_report_export'),
    path('payroll/', reports_access(views.payroll_report), name='payroll_report'),
    path('payroll/export/', export_access(views.payroll_report_export), name='payroll_report_export'),
    path('documents/', reports_access(views.documents_report), name='documents_report'),
    path('documents/export/', export_access(views.documents_report_export), name='documents_report_export'),
]
