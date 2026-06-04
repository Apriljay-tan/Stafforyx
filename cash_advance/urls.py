from django.urls import path

from . import views

app_name = 'cash_advance'

urlpatterns = [
    path('manage/', views.manage_ca, name='manage_ca'),
    path('manage/<int:pk>/', views.manage_ca_detail, name='manage_ca_detail'),
]
