from django.urls import path

from . import views

app_name = 'announcements'

urlpatterns = [
    path('', views.announcement_list, name='announcement_list'),
    path('add/', views.announcement_add, name='announcement_add'),
    path('<int:pk>/', views.announcement_detail, name='announcement_detail'),
    path('<int:pk>/edit/', views.announcement_edit, name='announcement_edit'),
    path('<int:pk>/delete/', views.announcement_delete, name='announcement_delete'),
]
