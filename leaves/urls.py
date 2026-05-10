from django.urls import path

from . import views

app_name = 'leaves'

urlpatterns = [
    path('', views.leave_request_list, name='leave_request_list'),
    path('add/', views.leave_request_add, name='leave_request_add'),
    path('<int:pk>/edit/', views.leave_request_edit, name='leave_request_edit'),
    path('<int:pk>/delete/', views.leave_request_delete, name='leave_request_delete'),
    path('<int:pk>/approve/', views.leave_request_approve, name='leave_request_approve'),
    path('<int:pk>/reject/', views.leave_request_reject, name='leave_request_reject'),
    path('types/', views.leave_type_list, name='leave_type_list'),
    path('types/add/', views.leave_type_add, name='leave_type_add'),
    path('types/<int:pk>/edit/', views.leave_type_edit, name='leave_type_edit'),
    path('types/<int:pk>/delete/', views.leave_type_delete, name='leave_type_delete'),
]
