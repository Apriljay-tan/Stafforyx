from django.urls import path

from . import views

app_name = 'portal'

urlpatterns = [
    # Employee self-service
    path('', views.portal_dashboard, name='dashboard'),
    path('payslips/', views.portal_payslip_list, name='payslip_list'),
    path('payslips/<int:pk>/', views.portal_payslip_detail, name='payslip_detail'),
    path('documents/', views.portal_documents, name='documents'),
    path('documents/<int:pk>/download/', views.portal_document_download, name='document_download'),
    path('announcements/', views.portal_announcements, name='announcements'),
    path('announcements/<int:pk>/', views.portal_announcement_detail, name='announcement_detail'),
    path('leaves/', views.portal_leave_list, name='leave_list'),
    path('leaves/new/', views.portal_leave_new, name='leave_new'),
    path('incidents/', views.portal_incident_list, name='incident_list'),
    path('incidents/new/', views.portal_incident_new, name='incident_new'),
    path('attendance/', views.portal_attendance, name='attendance'),
    path('time-clock/', views.portal_time_clock, name='time_clock'),
    # HR management
    path('manage/incidents/', views.manage_incidents, name='manage_incidents'),
    path('manage/incidents/<int:pk>/', views.manage_incident_detail, name='manage_incident_detail'),
]
