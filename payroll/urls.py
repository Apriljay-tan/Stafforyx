from django.urls import path
from accounts.access import module_access_required

from . import views

app_name = 'payroll'
payroll_access = module_access_required('can_manage_payroll')

urlpatterns = [
    path('', payroll_access(views.payroll_record_list), name='payroll_record_list'),
    path('records/add/', payroll_access(views.payroll_record_add), name='payroll_record_add'),
    path('records/<int:pk>/edit/', payroll_access(views.payroll_record_edit), name='payroll_record_edit'),
    path('records/<int:pk>/delete/', payroll_access(views.payroll_record_delete), name='payroll_record_delete'),
    path('periods/', payroll_access(views.payroll_period_list), name='payroll_period_list'),
    path('periods/add/', payroll_access(views.payroll_period_add), name='payroll_period_add'),
    path('periods/<int:pk>/edit/', payroll_access(views.payroll_period_edit), name='payroll_period_edit'),
    path('periods/<int:pk>/delete/', payroll_access(views.payroll_period_delete), name='payroll_period_delete'),
]
