from django.urls import path
from accounts.access import module_access_required

from . import views

app_name = 'documents'
documents_access = module_access_required('can_manage_documents')

urlpatterns = [
    path('', documents_access(views.employee_document_list), name='employee_document_list'),
    path('add/', documents_access(views.employee_document_add), name='employee_document_add'),
    path('<int:pk>/edit/', documents_access(views.employee_document_edit), name='employee_document_edit'),
    path('<int:pk>/delete/', documents_access(views.employee_document_delete), name='employee_document_delete'),
    path('<int:pk>/download/', documents_access(views.employee_document_download), name='employee_document_download'),
]
