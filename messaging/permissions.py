from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from accounts.company_access import get_accessible_companies, user_can_access_company
from employees.models import Employee


def user_can_manage_chat(user) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    profile = getattr(user, 'stafforyx_profile', None)
    if profile is None or not profile.is_active_stafforyx:
        return False
    return profile.can_manage_chat


def get_portal_employee(user):
    """Return the Employee linked to this user, mirroring portal.views._get_portal_employee."""
    if not user.is_authenticated:
        return None
    try:
        emp = user.employee_profile
        if emp is not None:
            return emp
    except Employee.DoesNotExist:
        pass
    profile = getattr(user, 'stafforyx_profile', None)
    if profile and profile.employee_id:
        return profile.employee
    return None


def employee_chat_enabled(employee) -> bool:
    if employee is None:
        return False
    return (
        employee.company.employee_chat_enabled
        and employee.can_use_chat
        and employee.status == 'active'
        and employee.user_id is not None
    )


def user_can_use_employee_chat(user) -> bool:
    employee = get_portal_employee(user)
    return employee_chat_enabled(employee)


def _chat_enabled_employees():
    return Employee.objects.filter(
        status='active',
        can_use_chat=True,
        company__employee_chat_enabled=True,
        user__isnull=False,
    )


def get_allowed_chat_contacts(user):
    employee = get_portal_employee(user)
    if not employee_chat_enabled(employee):
        return Employee.objects.none()

    enabled = _chat_enabled_employees()
    same_company = enabled.filter(company=employee.company).exclude(pk=employee.pk)
    allowed_company_ids = employee.allowed_chat_companies.values_list('pk', flat=True)
    cross_company = enabled.filter(company_id__in=allowed_company_ids)
    return (same_company | cross_company).distinct()


def user_can_access_conversation(user, conversation) -> bool:
    if not user.is_authenticated:
        return False

    if conversation.participants.filter(user=user, left_at__isnull=True).exists():
        return True

    if user_can_manage_chat(user) and user_can_access_company(user, conversation.company):
        return True

    return False


def get_support_display_name(company) -> str:
    if company.chat_support_display_name:
        return company.chat_support_display_name
    return settings.MESSAGING_DEFAULT_SUPPORT_NAME


def _admin_eligible_participant_user_ids(admin_user):
    """User IDs an admin may invite: chat-enabled employees in accessible companies + chat managers."""
    accessible_company_ids = get_accessible_companies(admin_user).values_list('pk', flat=True)
    employee_user_ids = _chat_enabled_employees().filter(
        company_id__in=accessible_company_ids,
    ).values_list('user_id', flat=True)
    manager_user_ids = User.objects.filter(
        stafforyx_profile__can_manage_chat=True,
        stafforyx_profile__is_active_stafforyx=True,
    ).values_list('pk', flat=True)
    return set(employee_user_ids) | set(manager_user_ids)


def validate_group_participant_users(creator_user, user_ids: list[int]) -> list:
    if not user_ids:
        raise ValidationError('At least one participant is required.')

    unique_ids = list(dict.fromkeys(user_ids))

    if user_can_manage_chat(creator_user):
        allowed_ids = _admin_eligible_participant_user_ids(creator_user)
    elif user_can_use_employee_chat(creator_user):
        allowed_ids = set(
            get_allowed_chat_contacts(creator_user).values_list('user_id', flat=True)
        )
    else:
        raise ValidationError('You do not have permission to create group conversations.')

    users = []
    for user_id in unique_ids:
        if user_id not in allowed_ids:
            raise ValidationError(f'User {user_id} is not an eligible chat participant.')
        try:
            users.append(User.objects.get(pk=user_id))
        except User.DoesNotExist:
            raise ValidationError(f'User {user_id} not found.') from None

    return users
