from django.urls import path
from . import views

app_name = 'companies'

urlpatterns = [
    path('<int:pk>/payslip-settings/', views.company_payslip_settings, name='payslip_settings'),
]
