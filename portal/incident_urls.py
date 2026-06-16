from django.urls import path

from . import views

app_name = 'incident_reports'

urlpatterns = [
    path('', views.manage_incidents, name='list'),
    path('<int:pk>/', views.manage_incident_detail, name='detail'),
]
