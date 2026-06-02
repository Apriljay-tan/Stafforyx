from django.urls import path

from . import views

app_name = 'overtime'

urlpatterns = [
    path('manage/', views.manage_overtime, name='manage_overtime'),
    path('manage/<int:pk>/', views.manage_overtime_detail, name='manage_overtime_detail'),
]
