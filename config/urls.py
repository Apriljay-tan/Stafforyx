from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from dashboard.views import dashboard_home

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', dashboard_home, name='dashboard_home'),
    path('employees/', include('employees.urls')),
    path('attendance/', include('attendance.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
