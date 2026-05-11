from datetime import date

from django.shortcuts import render, redirect
from django.contrib import messages

from .models import License
from .license_verifier import verify_signed_license
from .machine import get_machine_id


def license_status(request):
    license = License.objects.select_related('company').order_by('-created_at').first()
    return render(request, 'licenses/license_status.html', {
        'license': license,
        'machine_id': get_machine_id(),
    })


def activate_license(request):
    machine_id = get_machine_id()

    if request.method != 'POST':
        return render(request, 'licenses/license_activate.html', {
            'machine_id': machine_id,
        })

    key = request.POST.get('license_key', '').strip()
    if not key:
        messages.error(request, 'Please paste a license key.')
        return render(request, 'licenses/license_activate.html', {
            'machine_id': machine_id,
        })

    ok, result = verify_signed_license(key)
    if not ok:
        messages.error(request, f'Activation failed: {result}')
        return render(request, 'licenses/license_activate.html', {
            'submitted_key': key,
            'machine_id': machine_id,
        })

    payload = result

    # Machine ID check — only enforced when the license carries one
    payload_machine_id = payload.get('machine_id', '').strip()
    if payload_machine_id and payload_machine_id != machine_id:
        messages.error(
            request,
            'This license is not valid for this computer. '
            'Please request a license for this Machine ID.',
        )
        return render(request, 'licenses/license_activate.html', {
            'submitted_key': key,
            'machine_id': machine_id,
        })

    plan = payload['plan']
    valid_until_str = payload.get('valid_until') or ''
    if plan == 'lifetime' or not valid_until_str:
        status = 'active'
    else:
        try:
            valid_until_date = date.fromisoformat(valid_until_str)
            status = 'expired' if valid_until_date < date.today() else 'active'
        except ValueError:
            status = 'active'

    License.objects.update_or_create(
        license_id=payload['license_id'],
        defaults={
            'license_key':   key,
            'client_name':   payload.get('client_name', ''),
            'company_name':  payload.get('company_name', ''),
            'plan':          plan,
            'status':        status,
            'valid_from':    payload['valid_from'],
            'valid_until':   valid_until_str or None,
            'max_employees': payload['max_employees'],
            'machine_id':    payload_machine_id,
        },
    )

    if status == 'expired':
        messages.warning(
            request,
            f'License key accepted for {payload["client_name"]}, but it has already expired.',
        )
    else:
        messages.success(
            request,
            f'License activated successfully for {payload["client_name"]}.',
        )
    return redirect('licenses:license_status')
