import datetime

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from accounts.models import UserCompanyAccess, UserProfile
from companies.models import Company
from employees.models import Employee
from messaging.constants import TYPE_DIRECT
from messaging.models import Conversation, ConversationParticipant
from messaging.permissions import (
    employee_chat_enabled,
    get_allowed_chat_contacts,
    get_portal_employee,
    get_support_display_name,
    user_can_access_conversation,
    user_can_manage_chat,
    user_can_use_employee_chat,
    validate_group_participant_users,
)


def _make_company(name, email=None, **kwargs):
    return Company.objects.create(
        name=name,
        email=email or f'{name.lower().replace(" ", "")}@test.local',
        **kwargs,
    )


def _make_user(username, password='testpass123', is_superuser=False):
    if is_superuser:
        return User.objects.create_superuser(username=username, password=password)
    return User.objects.create_user(username=username, password=password)


def _grant_access(user, company, role='viewer'):
    return UserCompanyAccess.objects.create(user=user, company=company, role=role, is_active=True)


_emp_counter = 0


def _make_employee(company, user=None, **kwargs):
    global _emp_counter
    _emp_counter += 1
    defaults = {
        'company': company,
        'employee_id': f'TST{_emp_counter:03d}',
        'first_name': 'Test',
        'last_name': 'Emp',
        'email': f'emp{_emp_counter}@test.local',
        'date_hired': datetime.date(2024, 1, 1),
        'status': 'active',
    }
    defaults.update(kwargs)
    employee = Employee.objects.create(**defaults)
    if user is not None:
        employee.user = user
        employee.save(update_fields=['user'])
    return employee


def _enable_chat(company, employee):
    company.employee_chat_enabled = True
    company.save(update_fields=['employee_chat_enabled'])
    employee.can_use_chat = True
    employee.save(update_fields=['can_use_chat'])


class UserCanManageChatTests(TestCase):
    def setUp(self):
        self.user = _make_user('hr_user')
        self.profile = UserProfile.objects.create(user=self.user, can_manage_chat=False)

    def test_false_by_default(self):
        self.assertFalse(user_can_manage_chat(self.user))

    def test_true_when_can_manage_chat(self):
        self.profile.can_manage_chat = True
        self.profile.save(update_fields=['can_manage_chat'])
        self.assertTrue(user_can_manage_chat(self.user))

    def test_superuser_bypass(self):
        superuser = _make_user('su', is_superuser=True)
        self.assertTrue(user_can_manage_chat(superuser))

    def test_inactive_profile_denied(self):
        self.profile.can_manage_chat = True
        self.profile.is_active_stafforyx = False
        self.profile.save(update_fields=['can_manage_chat', 'is_active_stafforyx'])
        self.assertFalse(user_can_manage_chat(self.user))

    def test_can_manage_employees_alone_does_not_grant_chat(self):
        self.profile.can_manage_employees = True
        self.profile.save(update_fields=['can_manage_employees'])
        self.assertFalse(user_can_manage_chat(self.user))


class EmployeeChatEnabledTests(TestCase):
    def setUp(self):
        self.company = _make_company('Acme')
        self.user = _make_user('emp_user')
        self.employee = _make_employee(self.company, user=self.user)

    def test_false_when_company_switch_off(self):
        self.employee.can_use_chat = True
        self.employee.save(update_fields=['can_use_chat'])
        self.assertFalse(employee_chat_enabled(self.employee))

    def test_false_when_employee_toggle_off(self):
        self.company.employee_chat_enabled = True
        self.company.save(update_fields=['employee_chat_enabled'])
        self.assertFalse(employee_chat_enabled(self.employee))

    def test_false_when_no_linked_user(self):
        _enable_chat(self.company, self.employee)
        self.employee.user = None
        self.employee.save(update_fields=['user'])
        self.assertFalse(employee_chat_enabled(self.employee))

    def test_false_when_inactive(self):
        _enable_chat(self.company, self.employee)
        self.employee.status = 'inactive'
        self.employee.save(update_fields=['status'])
        self.assertFalse(employee_chat_enabled(self.employee))

    def test_true_when_all_conditions_met(self):
        _enable_chat(self.company, self.employee)
        self.assertTrue(employee_chat_enabled(self.employee))


class UserCanUseEmployeeChatTests(TestCase):
    def setUp(self):
        self.company = _make_company('Acme')
        self.user = _make_user('portal_user')
        self.employee = _make_employee(self.company, user=self.user)

    def test_false_without_chat_enabled(self):
        self.assertFalse(user_can_use_employee_chat(self.user))

    def test_true_when_employee_chat_enabled(self):
        _enable_chat(self.company, self.employee)
        self.assertTrue(user_can_use_employee_chat(self.user))


class GetPortalEmployeeTests(TestCase):
    def test_via_employee_user_link(self):
        company = _make_company('Acme')
        user = _make_user('linked')
        employee = _make_employee(company, user=user)
        self.assertEqual(get_portal_employee(user), employee)

    def test_via_user_profile_employee_fk(self):
        company = _make_company('Acme')
        user = _make_user('profile_linked')
        employee = _make_employee(company)
        UserProfile.objects.create(user=user, employee=employee)
        self.assertEqual(get_portal_employee(user), employee)


class GetAllowedChatContactsTests(TestCase):
    def setUp(self):
        self.company_a = _make_company('Company A')
        self.company_b = _make_company('Company B')
        self.viewer = _make_user('viewer')
        self.peer = _make_user('peer')
        self.cross = _make_user('cross')
        self.self_employee = _make_employee(self.company_a, user=self.viewer)
        self.same_company_peer = _make_employee(
            self.company_a, user=self.peer, first_name='Peer', last_name='One',
        )
        self.cross_company_peer = _make_employee(
            self.company_b, user=self.cross, first_name='Cross', last_name='Two',
        )
        _enable_chat(self.company_a, self.self_employee)
        _enable_chat(self.company_a, self.same_company_peer)
        _enable_chat(self.company_b, self.cross_company_peer)
        self.self_employee.allowed_chat_companies.add(self.company_b)

    def test_same_company_contacts_included(self):
        contacts = get_allowed_chat_contacts(self.viewer)
        self.assertIn(self.same_company_peer, contacts)
        self.assertNotIn(self.self_employee, contacts)

    def test_cross_company_when_allowed(self):
        contacts = get_allowed_chat_contacts(self.viewer)
        self.assertIn(self.cross_company_peer, contacts)

    def test_cross_company_excluded_without_m2m(self):
        self.self_employee.allowed_chat_companies.clear()
        contacts = get_allowed_chat_contacts(self.viewer)
        self.assertIn(self.same_company_peer, contacts)
        self.assertNotIn(self.cross_company_peer, contacts)

    def test_chat_disabled_peer_excluded(self):
        self.same_company_peer.can_use_chat = False
        self.same_company_peer.save(update_fields=['can_use_chat'])
        contacts = get_allowed_chat_contacts(self.viewer)
        self.assertNotIn(self.same_company_peer, contacts)


class UserCanAccessConversationTests(TestCase):
    def setUp(self):
        self.company = _make_company('Acme')
        self.admin = _make_user('admin')
        UserProfile.objects.create(user=self.admin, can_manage_chat=True)
        _grant_access(self.admin, self.company)
        self.employee_user = _make_user('emp')
        self.employee = _make_employee(self.company, user=self.employee_user)
        self.conv = Conversation.objects.create(
            company=self.company,
            conversation_type=TYPE_DIRECT,
            created_by=self.admin,
        )
        ConversationParticipant.objects.create(conversation=self.conv, user=self.employee_user)
        ConversationParticipant.objects.create(conversation=self.conv, user=self.admin)

    def test_active_participant_has_access(self):
        self.assertTrue(user_can_access_conversation(self.employee_user, self.conv))

    def test_non_participant_denied(self):
        outsider = _make_user('outsider')
        self.assertFalse(user_can_access_conversation(outsider, self.conv))

    def test_chat_manager_with_company_access_has_audit_access(self):
        auditor = _make_user('auditor')
        UserProfile.objects.create(user=auditor, can_manage_chat=True)
        _grant_access(auditor, self.company)
        self.assertTrue(user_can_access_conversation(auditor, self.conv))

    def test_chat_manager_without_company_access_denied(self):
        other_company = _make_company('Other')
        auditor = _make_user('auditor2')
        UserProfile.objects.create(user=auditor, can_manage_chat=True)
        _grant_access(auditor, other_company)
        self.assertFalse(user_can_access_conversation(auditor, self.conv))

    def test_left_participant_denied(self):
        participant = self.conv.participants.get(user=self.employee_user)
        participant.left_at = timezone.now()
        participant.save(update_fields=['left_at'])
        self.assertFalse(user_can_access_conversation(self.employee_user, self.conv))


class GetSupportDisplayNameTests(TestCase):
    def test_company_override(self):
        company = _make_company('Acme', chat_support_display_name='Company Desk')
        self.assertEqual(get_support_display_name(company), 'Company Desk')

    def test_global_default_when_blank(self):
        company = _make_company('Acme')
        self.assertEqual(get_support_display_name(company), 'HR Support')


class ValidateGroupParticipantUsersTests(TestCase):
    def setUp(self):
        self.company = _make_company('Acme')
        self.admin = _make_user('admin')
        UserProfile.objects.create(user=self.admin, can_manage_chat=True)
        _grant_access(self.admin, self.company)
        self.emp_user = _make_user('emp1')
        self.employee = _make_employee(self.company, user=self.emp_user)
        _enable_chat(self.company, self.employee)

    def test_employee_creator_validates_allowed_contacts(self):
        creator_user = _make_user('creator')
        creator = _make_employee(self.company, user=creator_user, employee_id='CR001')
        _enable_chat(self.company, creator)
        peer_user = _make_user('peer')
        peer = _make_employee(self.company, user=peer_user, employee_id='PR001')
        _enable_chat(self.company, peer)
        users = validate_group_participant_users(creator_user, [peer_user.pk])
        self.assertEqual([u.pk for u in users], [peer_user.pk])

    def test_employee_creator_rejects_out_of_scope(self):
        creator_user = _make_user('creator2')
        creator = _make_employee(self.company, user=creator_user, employee_id='CR002')
        _enable_chat(self.company, creator)
        outsider_user = _make_user('outsider')
        _make_employee(self.company, user=outsider_user, employee_id='OUT001')
        with self.assertRaises(ValidationError):
            validate_group_participant_users(creator_user, [outsider_user.pk])

    def test_admin_creator_accepts_chat_enabled_employee(self):
        users = validate_group_participant_users(self.admin, [self.emp_user.pk])
        self.assertEqual([u.pk for u in users], [self.emp_user.pk])

    def test_admin_creator_accepts_other_chat_manager(self):
        other_admin = _make_user('other_admin')
        UserProfile.objects.create(user=other_admin, can_manage_chat=True)
        users = validate_group_participant_users(self.admin, [other_admin.pk])
        self.assertEqual([u.pk for u in users], [other_admin.pk])

    def test_no_chat_access_raises(self):
        nobody = _make_user('nobody')
        with self.assertRaises(ValidationError):
            validate_group_participant_users(nobody, [self.emp_user.pk])
