from django.shortcuts import render
from .models import License


def license_status(request):
    license = License.objects.select_related('company').order_by('-created_at').first()
    return render(request, 'licenses/license_status.html', {'license': license})
