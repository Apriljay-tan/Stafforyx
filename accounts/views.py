from django.contrib import messages
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404, redirect, render

from .access import super_admin_required
from .forms import StafforyxUserCreationForm, UserProfileForm
from .models import UserProfile


def permission_denied_view(request, exception=None):
    return render(request, '403.html', status=403)


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
