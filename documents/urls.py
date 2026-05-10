from django.urls import path

from . import views

app_name = 'documents'

urlpatterns = [
    path('', views.employee_document_list, name='employee_document_list'),
    path('add/', views.employee_document_add, name='employee_document_add'),
    path('<int:pk>/edit/', views.employee_document_edit, name='employee_document_edit'),
    path('<int:pk>/delete/', views.employee_document_delete, name='employee_document_delete'),
]
