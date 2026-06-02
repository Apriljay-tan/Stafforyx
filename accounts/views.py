from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .access import super_admin_required
from .company_access import get_accessible_companies, user_can_access_company
from .forms import StafforyxUserCreationForm, UserProfileForm
from .models import UserProfile


def permission_denied_view(request, exception=None):
    from .access import is_employee_only_user
    return render(
        request,
        '403.html',
        {'is_employee_only': is_employee_only_user(request.user)},
        status=403,
    )


@login_required
@require_POST
def select_company(request):
    """Store the chosen company in the session. Called via POST from any page."""
    company_id = request.POST.get('company_id')
    next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or '/'

    if not company_id:
        request.session.pop('selected_company_id', None)
        return redirect(next_url)

    try:
        company_id = int(company_id)
    except (TypeError, ValueError):
        return redirect(next_url)

    from companies.models import Company
    try:
        company = Company.objects.get(pk=company_id)
    except Company.DoesNotExist:
        return redirect(next_url)

    if not user_can_access_company(request.user, company):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied

    request.session['selected_company_id'] = company_id
    return redirect(next_url)


@super_admin_required
def user_list(request):
    users = User.objects.select_related('stafforyx_profile').order_by('username')
    return render(request, 'accounts/user_list.html', {'users': users})


@super_admin_required
def user_add(request):
    user_form = StafforyxUserCreationForm(request.POST or None)
    profile_form = UserProfileForm(request.POST or None)

    if request.method == 'POST' and user_form.is_valid() and profile_form.is_valid():
        user = user_form.save()
        profile = profile_form.save(commit=False)
        profile.user = user
        profile.save()
        messages.success(request, f'User "{user.username}" created successfully.')
        return redirect('accounts:user_list')

    return render(request, 'accounts/user_form.html', {
        'user_form': user_form,
        'profile_form': profile_form,
        'action': 'Add',
    })


@super_admin_required
def user_edit(request, pk):
    user = get_object_or_404(User, pk=pk)
    profile, _created = UserProfile.objects.get_or_create(user=user)
    profile_form = UserProfileForm(request.POST or None, instance=profile)

    if request.method == 'POST' and profile_form.is_valid():
        profile_form.save()
        messages.success(request, f'Access updated for "{user.username}".')
        return redirect('accounts:user_list')

    return render(request, 'accounts/user_form.html', {
        'managed_user': user,
        'profile_form': profile_form,
        'action': 'Edit',
    })
