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

    return {
        'accessible_companies': accessible,
        'selected_company': selected,
    }
