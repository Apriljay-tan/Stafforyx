import re

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


DEFAULT_SIDEBAR_COLOR = '#0D1B2A'
DEFAULT_SIDEBAR_ACCENT = '#1565C0'

# Curated, contrast-checked presets surfaced in the Theme page.
SIDEBAR_PRESETS = [
    {'name': 'Midnight Navy', 'base': '#0D1B2A', 'accent': '#1565C0'},
    {'name': 'Slate',         'base': '#1E293B', 'accent': '#3B82F6'},
    {'name': 'Forest',        'base': '#0F2A22', 'accent': '#10B981'},
    {'name': 'Plum',          'base': '#2A1330', 'accent': '#A855F7'},
    {'name': 'Espresso',      'base': '#241A14', 'accent': '#D97706'},
    {'name': 'Teal Deep',     'base': '#06363B', 'accent': '#06B6D4'},
    {'name': 'Crimson',       'base': '#2C0E13', 'accent': '#EF4444'},
    {'name': 'Graphite',      'base': '#17181C', 'accent': '#6366F1'},
]

_HEX_RE = re.compile(r'^#[0-9a-fA-F]{6}$')


@login_required
def theme(request):
    """Let any authenticated user customize their own sidebar theme."""
    profile, _created = UserProfile.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        if 'reset' in request.POST:
            profile.sidebar_color = ''
            profile.sidebar_accent = ''
            profile.save(update_fields=['sidebar_color', 'sidebar_accent'])
            messages.success(request, 'Theme reset to the default.')
            return redirect('accounts:theme')

        color = (request.POST.get('sidebar_color') or '').strip().upper()
        accent = (request.POST.get('sidebar_accent') or '').strip().upper()

        if not _HEX_RE.match(color):
            messages.error(request, 'Please choose a valid sidebar color.')
            return redirect('accounts:theme')

        if accent and not _HEX_RE.match(accent):
            accent = ''

        profile.sidebar_color = color
        profile.sidebar_accent = accent
        profile.save(update_fields=['sidebar_color', 'sidebar_accent'])
        messages.success(request, 'Theme saved.')
        return redirect('accounts:theme')

    return render(request, 'accounts/theme.html', {
        'presets': SIDEBAR_PRESETS,
        'current_color': profile.sidebar_color or DEFAULT_SIDEBAR_COLOR,
        'current_accent': profile.sidebar_accent or DEFAULT_SIDEBAR_ACCENT,
        'is_custom': bool(profile.sidebar_color),
        'default_color': DEFAULT_SIDEBAR_COLOR,
        'default_accent': DEFAULT_SIDEBAR_ACCENT,
    })


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
