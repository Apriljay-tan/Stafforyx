from django.urls import path

from . import views

app_name = 'payroll'

urlpatterns = [
    path('', views.payroll_record_list, name='payroll_record_list'),
    path('records/add/', views.payroll_record_add, name='payroll_record_add'),
    path('records/<int:pk>/edit/', views.payroll_record_edit, name='payroll_record_edit'),
    path('records/<int:pk>/delete/', views.payroll_record_delete, name='payroll_record_delete'),
    path('periods/', views.payroll_period_list, name='payroll_period_list'),
    path('periods/add/', views.payroll_period_add, name='payroll_period_add'),
    path('periods/<int:pk>/edit/', views.payroll_period_edit, name='payroll_period_edit'),
    path('periods/<int:pk>/delete/', views.payroll_period_delete, name='payroll_period_delete'),
]
