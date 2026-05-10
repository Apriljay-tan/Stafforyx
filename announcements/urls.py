from django.urls import path
from accounts.access import module_access_required

from . import views

app_name = 'announcements'
announcements_access = module_access_required('can_manage_announcements')

urlpatterns = [
    path('', announcements_access(views.announcement_list), name='announcement_list'),
    path('add/', announcements_access(views.announcement_add), name='announcement_add'),
    path('<int:pk>/', announcements_access(views.announcement_detail), name='announcement_detail'),
    path('<int:pk>/edit/', announcements_access(views.announcement_edit), name='announcement_edit'),
    path('<int:pk>/delete/', announcements_access(views.announcement_delete), name='announcement_delete'),
]
