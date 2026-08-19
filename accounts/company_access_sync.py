"""Sync UserCompanyAccess rows from Stafforyx user management forms."""

from companies.models import Company

from .models import UserCompanyAccess, UserProfile

_PROFILE_TO_ACCESS_ROLE = {
    'super_admin': 'owner',
    'hr_admin': 'hr_admin',
    'manager': 'company_admin',
    'employee': 'viewer',
}


def get_managed_company_ids(user):
    """Return company PKs currently assigned through UserCompanyAccess."""
    return list(
        UserCompanyAccess.objects
        .filter(user=user, is_active=True)
        .values_list('company_id', flat=True)
    )


def sync_user_company_access(user, company_ids, profile=None):
    """
    Replace the user's active company assignments with *company_ids*.

    Also keeps profile.company in sync when exactly one company is selected.
    """
    profile = profile or getattr(user, 'stafforyx_profile', None)
    role = getattr(profile, 'role', None) or 'viewer'
    access_role = _PROFILE_TO_ACCESS_ROLE.get(role, 'viewer')

    cleaned_ids = []
    for company_id in company_ids or []:
        try:
            cleaned_ids.append(int(company_id))
        except (TypeError, ValueError):
            continue

    valid_ids = set(
        Company.objects.filter(pk__in=cleaned_ids).values_list('pk', flat=True)
    )

    UserCompanyAccess.objects.filter(user=user).exclude(
        company_id__in=valid_ids,
    ).delete()

    for company_id in sorted(valid_ids):
        UserCompanyAccess.objects.update_or_create(
            user=user,
            company_id=company_id,
            defaults={'role': access_role, 'is_active': True},
        )

    if profile is not None:
        if len(valid_ids) == 1:
            only_id = next(iter(valid_ids))
            if profile.company_id != only_id:
                profile.company_id = only_id
                profile.save(update_fields=['company'])
        elif profile.company_id and profile.company_id not in valid_ids:
            profile.company = None
            profile.save(update_fields=['company'])
