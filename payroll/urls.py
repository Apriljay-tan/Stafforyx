from django.urls import path
from accounts.access import module_access_required

from . import views

app_name = 'payroll'
payroll_access = module_access_required('can_manage_payroll')

urlpatterns = [
    # Payroll records
    path('', payroll_access(views.payroll_record_list), name='payroll_record_list'),
    path('generate/', payroll_access(views.payroll_generate), name='payroll_generate'),
    path('records/add/', payroll_access(views.payroll_record_add), name='payroll_record_add'),
    path('records/<int:pk>/edit/', payroll_access(views.payroll_record_edit), name='payroll_record_edit'),
    path('records/<int:pk>/delete/', payroll_access(views.payroll_record_delete), name='payroll_record_delete'),

    # Payslip
    path('records/<int:pk>/payslip/', payroll_access(views.payslip_view), name='payslip_view'),
    path('records/<int:pk>/payslip/send/', payroll_access(views.payslip_send_email), name='payslip_send_email'),

    # Adjustments
    path('records/<int:record_pk>/adjustments/add/', payroll_access(views.adjustment_add), name='adjustment_add'),
    path('adjustments/<int:pk>/delete/', payroll_access(views.adjustment_delete), name='adjustment_delete'),

    # Payroll periods
    path('periods/', payroll_access(views.payroll_period_list), name='payroll_period_list'),
    path('periods/add/', payroll_access(views.payroll_period_add), name='payroll_period_add'),
    path('periods/<int:pk>/edit/', payroll_access(views.payroll_period_edit), name='payroll_period_edit'),
    path('periods/<int:pk>/delete/', payroll_access(views.payroll_period_delete), name='payroll_period_delete'),
]
