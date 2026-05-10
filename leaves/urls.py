from django.urls import path
from accounts.access import module_access_required

from . import views

app_name = 'leaves'
leaves_access = module_access_required('can_manage_leaves')

urlpatterns = [
    path('', leaves_access(views.leave_request_list), name='leave_request_list'),
    path('add/', leaves_access(views.leave_request_add), name='leave_request_add'),
    path('<int:pk>/edit/', leaves_access(views.leave_request_edit), name='leave_request_edit'),
    path('<int:pk>/delete/', leaves_access(views.leave_request_delete), name='leave_request_delete'),
    path('<int:pk>/approve/', leaves_access(views.leave_request_approve), name='leave_request_approve'),
    path('<int:pk>/reject/', leaves_access(views.leave_request_reject), name='leave_request_reject'),
    path('types/', leaves_access(views.leave_type_list), name='leave_type_list'),
    path('types/add/', leaves_access(views.leave_type_add), name='leave_type_add'),
    path('types/<int:pk>/edit/', leaves_access(views.leave_type_edit), name='leave_type_edit'),
    path('types/<int:pk>/delete/', leaves_access(views.leave_type_delete), name='leave_type_delete'),
]
