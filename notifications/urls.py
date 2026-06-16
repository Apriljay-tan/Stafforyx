from django.urls import path

from . import views

app_name = 'notifications'

urlpatterns = [
    path('', views.notification_list, name='list'),
    path('api/unread/', views.unread_api, name='unread_api'),
    path('<int:pk>/open/', views.open_notification, name='open'),
    path('mark-all-read/', views.mark_all_read, name='mark_all_read'),
]
