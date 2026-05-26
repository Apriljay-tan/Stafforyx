from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from dashboard.views import dashboard_home
from accounts.access import module_access_required

admin.site.site_header = "Stafforyx HR"
admin.site.site_title = "Stafforyx HR Admin"
admin.site.index_title = "Admin Panel"

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', module_access_required('can_access_dashboard')(dashboard_home), name='dashboard_home'),
    path('accounts/', include('accounts.urls')),
    path('employees/', include('employees.urls')),
    path('attendance/', include('attendance.urls')),
    path('leaves/', include('leaves.urls')),
    path('payroll/', include('payroll.urls')),
    path('documents/', include('documents.urls')),
    path('announcements/', include('announcements.urls')),
    path('reports/', include('reports.urls')),
    path('licenses/', include('licenses.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

handler403 = 'accounts.views.permission_denied_view'
