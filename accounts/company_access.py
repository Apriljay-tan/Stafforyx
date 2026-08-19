"""
Company-scoped access helpers.

All views that touch company data should use these helpers to enforce
that users only see/edit data belonging to companies they are assigned to.

Superusers bypass all company restrictions and see everything.
"""

from companies.models import Company


def _accessible_company_id_set(user):
    """Return the set of company PKs a user may access."""
    if not user.is_authenticated:
        return set()

    if user.is_superuser:
        return set(Company.objects.values_list('pk', flat=True))

    profile = getattr(user, 'stafforyx_profile', None)
    if profile and profile.role == 'super_admin':
        return set(Company.objects.values_list('pk', flat=True))

    from .models import UserCompanyAccess

    company_ids = set(
        UserCompanyAccess.objects
        .filter(user=user, is_active=True)
        .values_list('company_id', flat=True)
    )
    # Legacy single-company assignment on the profile still grants access.
    if profile and profile.company_id:
        company_ids.add(profile.company_id)
    return company_ids


def get_accessible_companies(user):
    """Return a queryset of Company objects the user is permitted to access."""
    if not user.is_authenticated:
        return Company.objects.none()

    if user.is_superuser:
        return Company.objects.all()

    profile = getattr(user, 'stafforyx_profile', None)
    if profile and profile.role == 'super_admin':
        return Company.objects.all()

    company_ids = _accessible_company_id_set(user)
    if not company_ids:
        return Company.objects.none()
    return Company.objects.filter(pk__in=company_ids).order_by('name')


def user_can_access_company(user, company):
    """Return True if the user is allowed to access the given company."""
    if not user.is_authenticated:
        return False

    if user.is_superuser:
        return True

    profile = getattr(user, 'stafforyx_profile', None)
    if profile and profile.role == 'super_admin':
        return True

    return company.pk in _accessible_company_id_set(user)


def get_primary_company_for_user(user):
    """
    Return the single Company a non-superuser is primarily assigned to,
    or None if the user has no active assignment or has multiple.

    For superusers this always returns None (they use the session selector).
    """
    if not user.is_authenticated or user.is_superuser:
        return None

    profile = getattr(user, 'stafforyx_profile', None)
    if profile and profile.role == 'super_admin':
        return None

    from .models import UserCompanyAccess
    accesses = UserCompanyAccess.objects.filter(
        user=user, is_active=True,
    ).select_related('company')
    access_count = accesses.count()
    if access_count > 1:
        return None
    if access_count == 1:
        return accesses.first().company

    if profile and profile.company_id:
        return profile.company

    return None


def filter_queryset_by_user_companies(queryset, user, company_field='company'):
    """
    Restrict *queryset* to rows whose `company_field` FK is in the user's
    accessible companies.  Superusers get the queryset unfiltered.

    When *queryset* is of the Company model itself, it is filtered by primary
    key instead of by a (non-existent) ``company`` field — this lets callers
    pass ``Company.objects.all()`` safely to build a company picker.
    """
    if not user.is_authenticated:
        return queryset.none()

    if user.is_superuser:
        return queryset

    profile = getattr(user, 'stafforyx_profile', None)
    if profile and profile.role == 'super_admin':
        return queryset

    accessible = get_accessible_companies(user)
    if queryset.model is Company:
        return queryset.filter(pk__in=accessible)
    return queryset.filter(**{f'{company_field}__in': accessible})


def get_selected_company_from_request(request):
    """
    Return the Company currently selected for this session, or None.

    Selection priority:
      1. Session key 'selected_company_id'
      2. Derived from get_primary_company_for_user (single-assignment users)
      3. None (caller must handle this — usually show a selector)
    """
    if not request.user.is_authenticated:
        return None

    if request.user.is_superuser:
        company_id = request.session.get('selected_company_id')
        if company_id:
            try:
                return Company.objects.get(pk=company_id)
            except Company.DoesNotExist:
                del request.session['selected_company_id']
        return None

    primary = get_primary_company_for_user(request.user)
    if primary:
        return primary

    company_id = request.session.get('selected_company_id')
    if company_id:
        accessible = get_accessible_companies(request.user)
        try:
            return accessible.get(pk=company_id)
        except Company.DoesNotExist:
            del request.session['selected_company_id']

    return None


def user_can_view_all_accessible_companies(user):
    """True when the company switcher may include an 'All Companies' option."""
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    profile = getattr(user, 'stafforyx_profile', None)
    if profile and profile.role == 'super_admin':
        return True
    return get_accessible_companies(user).count() > 1


def should_show_company_column(user, selected_company):
    """Show a Company column when viewing rows from multiple branches at once."""
    return selected_company is None and get_accessible_companies(user).count() > 1
