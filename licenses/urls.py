from django.urls import path
from . import views

app_name = 'licenses'

urlpatterns = [
    path('status/', views.license_status, name='license_status'),
]
