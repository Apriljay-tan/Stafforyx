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
    path('notifications/seen/', views.portal_notifications_seen, name='notifications_seen'),
    path('leaves/', views.portal_leave_list, name='leave_list'),
    path('leaves/new/', views.portal_leave_new, name='leave_new'),
    path('incidents/', views.portal_incident_list, name='incident_list'),
    path('incidents/new/', views.portal_incident_new, name='incident_new'),
    path('attendance/', views.portal_attendance, name='attendance'),
    path('time-clock/', views.portal_time_clock, name='time_clock'),
    path('overtime/', views.portal_overtime_list, name='overtime_list'),
    path('overtime/new/', views.portal_overtime_new, name='overtime_new'),
    path('cash-advance/', views.portal_ca_list, name='ca_list'),
    path('cash-advance/new/', views.portal_ca_new, name='ca_new'),
    path('cash-advance/<int:pk>/edit/', views.portal_ca_edit, name='ca_edit'),
    path('cash-advance/<int:pk>/cancel/', views.portal_ca_cancel, name='ca_cancel'),
    # HR management
    path('manage/incidents/', views.manage_incidents, name='manage_incidents'),
    path('manage/incidents/<int:pk>/', views.manage_incident_detail, name='manage_incident_detail'),
]
