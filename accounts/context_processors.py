from .company_access import get_accessible_companies, get_selected_company_from_request


def company_context(request):
    """
    Inject into every template:
      - accessible_companies   — queryset the current user can switch to
      - selected_company       — Company currently active in the session (or None)
    """
    if not request.user.is_authenticated:
        return {}

    accessible = get_accessible_companies(request.user)
    selected = get_selected_company_from_request(request)
    profile = getattr(request.user, 'stafforyx_profile', None)
    is_super_admin = request.user.is_superuser or (profile and profile.role == 'super_admin')
    can_manage_license = is_super_admin or (profile and profile.can_manage_license)
    can_manage_settings = is_super_admin or (profile and profile.can_manage_settings)

    return {
        'accessible_companies': accessible,
        'selected_company': selected,
        'stafforyx_profile': profile,
        'is_super_admin_user': is_super_admin,
        'can_manage_license_user': can_manage_license,
        'can_manage_settings_user': can_manage_settings,
    }
