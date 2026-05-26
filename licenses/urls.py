from django.urls import path
from accounts.access import module_access_required

from . import views

app_name = 'licenses'
_license_access = module_access_required('can_manage_license')

urlpatterns = [
    path('status/',   _license_access(views.license_status),   name='license_status'),
    path('activate/', _license_access(views.activate_license), name='activate_license'),
]
