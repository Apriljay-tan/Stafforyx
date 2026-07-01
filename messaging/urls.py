from django.urls import path

from . import views

app_name = 'messaging'

urlpatterns = [
    path('', views.inbox, name='inbox'),
    path('new/', views.compose, name='compose'),
    path('audit/', views.audit_list, name='audit_list'),
    path('audit/<int:pk>/', views.audit_detail, name='audit_detail'),
    path('api/unread/', views.unread_api, name='unread_api'),
    path('<int:pk>/', views.thread, name='thread'),
    path('<int:pk>/archive/', views.archive_conversation_view, name='archive'),
    path('api/thread/<int:pk>/', views.thread_api, name='thread_api'),
]
