# Internal Chat (Messaging) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a company-scoped internal messaging system with admin persona chat, employee portal chat, group messaging, silent admin audit, and HTTP polling — without WebSockets, attachments, or employee-visible monitoring notices.

**Architecture:** New `messaging` Django app holds conversations, participants, messages, and read state. Permission fields on `Company`, `Employee`, and `UserProfile` gate access. `messaging/permissions.py` centralizes rules; `messaging/services.py` handles send/receive/search/archive. Admin UI at `/messaging/`; portal UI at `/portal/messages/`. Persona display is computed at render time; `Message.sender_user` always stores the real sender for audit.

**Tech Stack:** Django 6.0.5, SQLite (local) / PostgreSQL (production via env), Bootstrap 5 templates, `fetch` polling. Tests via `./venv/Scripts/python.exe manage.py test`.

**Reference spec:** `docs/superpowers/specs/2026-07-01-internal-chat-design.md`

**Test command convention:** `./venv/Scripts/python.exe manage.py test <dotted.path> -v 2`

**Do not touch:** `.env`, `db.sqlite3`, production-only settings files.

---

## File map (created/modified)

| File | Responsibility |
|---|---|
| `messaging/` (new app) | Models, permissions, services, views, APIs, tests |
| `companies/models.py` | `employee_chat_enabled`, `chat_support_display_name` |
| `employees/models.py` | `can_use_chat`, `allowed_chat_companies` M2M |
| `accounts/models.py` | `can_manage_chat` |
| `accounts/middleware.py` | Allow `/portal/messages/` for employee-only users |
| `accounts/forms.py` or `accounts/user_form` fields | `can_manage_chat` on user form |
| `employees/forms.py` | Chat settings on employee form |
| `companies/admin.py` | Chat fields on Company admin |
| `config/settings.py` | `INSTALLED_APPS`, settings constants, context processor |
| `config/urls.py` | `path('messaging/', ...)` |
| `portal/urls.py` | Portal message routes |
| `templates/base.html` | Admin Messages nav + poll JS hook |
| `templates/portal/base.html` | Portal Messages nav + poll JS hook |
| `templates/messaging/*.html` | Admin inbox, thread, compose, audit |
| `templates/portal/messages/*.html` | Portal inbox, thread, compose |

---

## Task 1: Scaffold `messaging` app + constants

**Files:**
- Create: `messaging/__init__.py`, `messaging/apps.py`, `messaging/admin.py`, `messaging/migrations/__init__.py`
- Create: `messaging/constants.py`
- Create: `messaging/tests/__init__.py`, `messaging/tests/test_constants.py`
- Modify: `config/settings.py`

- [ ] **Step 1: Write the failing test**

`messaging/tests/test_constants.py`:
```python
from django.test import SimpleTestCase

from messaging.constants import (
    TYPE_ADMIN_SUPPORT,
    TYPE_DIRECT,
    TYPE_GROUP,
    CONVERSATION_TYPE_VALUES,
    ROLE_ADMIN,
    ROLE_GROUP_CREATOR,
    ROLE_MEMBER,
)


class ConstantsTests(SimpleTestCase):
    def test_conversation_types(self):
        self.assertEqual(CONVERSATION_TYPE_VALUES, [TYPE_DIRECT, TYPE_ADMIN_SUPPORT, TYPE_GROUP])

    def test_roles_exist(self):
        self.assertEqual(ROLE_MEMBER, 'member')
        self.assertEqual(ROLE_GROUP_CREATOR, 'group_creator')
        self.assertEqual(ROLE_ADMIN, 'admin')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe manage.py test messaging.tests.test_constants -v 2`
Expected: FAIL — `ModuleNotFoundError: No module named 'messaging'`.

- [ ] **Step 3: Create app scaffold**

`messaging/__init__.py`: empty.

`messaging/migrations/__init__.py`: empty.

`messaging/apps.py`:
```python
from django.apps import AppConfig


class MessagingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'messaging'
    verbose_name = 'Messaging'
```

`messaging/admin.py`:
```python
from django.contrib import admin

# Model admins registered in Task 4.
```

`messaging/constants.py`:
```python
TYPE_DIRECT = 'direct'
TYPE_ADMIN_SUPPORT = 'admin_support'
TYPE_GROUP = 'group'

CONVERSATION_TYPE_CHOICES = [
    (TYPE_DIRECT, 'Direct'),
    (TYPE_ADMIN_SUPPORT, 'Admin Support'),
    (TYPE_GROUP, 'Group'),
]
CONVERSATION_TYPE_VALUES = [c[0] for c in CONVERSATION_TYPE_CHOICES]

ROLE_MEMBER = 'member'
ROLE_GROUP_CREATOR = 'group_creator'
ROLE_ADMIN = 'admin'

PARTICIPANT_ROLE_CHOICES = [
    (ROLE_MEMBER, 'Member'),
    (ROLE_GROUP_CREATOR, 'Group Creator'),
    (ROLE_ADMIN, 'Admin'),
]

MAX_MESSAGE_BODY_LENGTH = 5000
```

- [ ] **Step 4: Register app + settings constants**

In `config/settings.py`, add to `INSTALLED_APPS` after `"notifications"`:
```python
"messaging",
```

Add near other project settings:
```python
MESSAGING_DEFAULT_SUPPORT_NAME = 'HR Support'
MESSAGING_POLL_INTERVAL_MS = 15000
```

- [ ] **Step 5: Run test to verify it passes**

Run: `./venv/Scripts/python.exe manage.py test messaging.tests.test_constants -v 2`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add messaging/ config/settings.py
git commit -m "feat(messaging): scaffold messaging app and constants"
```

---

## Task 2: Permission fields on Company, Employee, UserProfile

**Files:**
- Modify: `companies/models.py`, `employees/models.py`, `accounts/models.py`
- Create: migrations via makemigrations
- Create: `messaging/tests/test_model_fields.py`
- Modify: `companies/admin.py` (fieldsets for chat settings)

- [ ] **Step 1: Write the failing test**

`messaging/tests/test_model_fields.py`:
```python
from django.test import TestCase

from accounts.models import UserProfile
from companies.models import Company
from employees.models import Employee


class ChatModelFieldTests(TestCase):
    def test_company_chat_defaults(self):
        company = Company.objects.create(name='Acme', email='a@acme.test')
        self.assertFalse(company.employee_chat_enabled)
        self.assertEqual(company.chat_support_display_name, '')

    def test_employee_chat_defaults(self):
        company = Company.objects.create(name='Acme', email='a@acme.test')
        employee = Employee.objects.create(
            company=company,
            employee_id='E001',
            first_name='Ana',
            last_name='Reyes',
            email='ana@acme.test',
        )
        self.assertFalse(employee.can_use_chat)
        self.assertEqual(employee.allowed_chat_companies.count(), 0)

    def test_user_profile_can_manage_chat_default(self):
        from django.contrib.auth.models import User
        user = User.objects.create_user('hr1', password='x')
        profile = UserProfile.objects.create(user=user)
        self.assertFalse(profile.can_manage_chat)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe manage.py test messaging.tests.test_model_fields -v 2`
Expected: FAIL — `employee_chat_enabled` or `can_use_chat` attribute missing.

- [ ] **Step 3: Add model fields**

`companies/models.py` — add after payslip fields block (or end of model before Meta):
```python
    employee_chat_enabled = models.BooleanField(
        default=False,
        help_text='Master switch: allow employee portal chat for this company.',
    )
    chat_support_display_name = models.CharField(
        max_length=100,
        blank=True,
        default='',
        help_text='Persona name shown to employees in admin support chats. Blank uses global default.',
    )
```

`employees/models.py` — add on `Employee`:
```python
    can_use_chat = models.BooleanField(
        default=False,
        help_text='Allow this employee to use portal chat when company chat is enabled.',
    )
    allowed_chat_companies = models.ManyToManyField(
        'companies.Company',
        blank=True,
        related_name='chat_enabled_employees',
        help_text='Other companies this employee may chat with (cross-company).',
    )
```

`accounts/models.py` — add on `UserProfile` after other `can_manage_*` fields:
```python
    can_manage_chat = models.BooleanField(
        default=False,
        help_text='Access admin chat inbox, message employees, create official groups, and audit.',
    )
```

`companies/admin.py` — add fieldset or fields list including `employee_chat_enabled` and `chat_support_display_name`.

- [ ] **Step 4: Create and run migrations**

Run:
```bash
./venv/Scripts/python.exe manage.py makemigrations companies employees accounts
./venv/Scripts/python.exe manage.py migrate
```

- [ ] **Step 5: Run tests**

Run: `./venv/Scripts/python.exe manage.py test messaging.tests.test_model_fields -v 2`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add companies/ employees/ accounts/ messaging/tests/test_model_fields.py
git commit -m "feat(messaging): add chat permission fields to core models"
```

---

## Task 3: Messaging models

**Files:**
- Create: `messaging/models.py`
- Create: migration
- Create: `messaging/tests/test_models.py`
- Modify: `messaging/admin.py`

- [ ] **Step 1: Write the failing test**

`messaging/tests/test_models.py`:
```python
from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from companies.models import Company
from employees.models import Employee
from messaging.constants import TYPE_ADMIN_SUPPORT, TYPE_DIRECT
from messaging.models import Conversation, ConversationParticipant, Message, ConversationReadState


class MessagingModelTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='Acme', email='a@acme.test')
        self.admin = User.objects.create_user('admin1', password='x')
        self.employee_user = User.objects.create_user('emp1', password='x')
        self.employee = Employee.objects.create(
            company=self.company,
            employee_id='E001',
            first_name='Ana',
            last_name='Reyes',
            email='ana@acme.test',
            user=self.employee_user,
        )

    def test_create_admin_support_conversation(self):
        conv = Conversation.objects.create(
            company=self.company,
            conversation_type=TYPE_ADMIN_SUPPORT,
            created_by=self.admin,
        )
        ConversationParticipant.objects.create(
            conversation=conv,
            user=self.employee_user,
            employee=self.employee,
        )
        ConversationParticipant.objects.create(
            conversation=conv,
            user=self.admin,
            role='admin',
        )
        msg = Message.objects.create(
            conversation=conv,
            sender_user=self.admin,
            body='Hello',
        )
        self.assertEqual(msg.sender_user, self.admin)
        self.assertIsNone(msg.deleted_at)

    def test_read_state_unique(self):
        conv = Conversation.objects.create(
            company=self.company,
            conversation_type=TYPE_DIRECT,
            created_by=self.admin,
        )
        ConversationReadState.objects.create(
            conversation=conv,
            user=self.admin,
            last_read_at=timezone.now(),
        )
        self.assertEqual(ConversationReadState.objects.filter(conversation=conv, user=self.admin).count(), 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe manage.py test messaging.tests.test_models -v 2`
Expected: FAIL — `No module named 'messaging.models'`.

- [ ] **Step 3: Implement models**

`messaging/models.py`:
```python
from django.contrib.auth.models import User
from django.db import models

from companies.models import Company
from employees.models import Employee

from .constants import (
    CONVERSATION_TYPE_CHOICES,
    MAX_MESSAGE_BODY_LENGTH,
    PARTICIPANT_ROLE_CHOICES,
)


class Conversation(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='conversations')
    conversation_type = models.CharField(max_length=20, choices=CONVERSATION_TYPE_CHOICES)
    title = models.CharField(max_length=150, blank=True, default='')
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='created_conversations')
    is_archived = models.BooleanField(default=False)
    archived_at = models.DateTimeField(null=True, blank=True)
    archived_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='archived_conversations',
    )
    last_message_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-last_message_at', '-created_at']
        indexes = [
            models.Index(fields=['company', '-last_message_at']),
            models.Index(fields=['conversation_type', 'company']),
        ]

    def __str__(self):
        return self.title or f'{self.get_conversation_type_display()} #{self.pk}'


class ConversationParticipant(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='participants')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='conversation_participations')
    employee = models.ForeignKey(Employee, null=True, blank=True, on_delete=models.SET_NULL)
    role = models.CharField(max_length=20, choices=PARTICIPANT_ROLE_CHOICES, default='member')
    joined_at = models.DateTimeField(auto_now_add=True)
    left_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [('conversation', 'user')]
        indexes = [models.Index(fields=['user', 'left_at'])]

    @property
    def is_active(self):
        return self.left_at is None


class Message(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='messages')
    sender_user = models.ForeignKey(User, on_delete=models.PROTECT, related_name='sent_messages')
    body = models.TextField(max_length=MAX_MESSAGE_BODY_LENGTH)
    created_at = models.DateTimeField(auto_now_add=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='deleted_messages',
    )

    class Meta:
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['conversation', 'created_at']),
        ]

    def __str__(self):
        return f'Message {self.pk} in conversation {self.conversation_id}'


class ConversationReadState(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='read_states')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='conversation_read_states')
    last_read_at = models.DateTimeField()

    class Meta:
        unique_together = [('conversation', 'user')]
```

Register read-only admins in `messaging/admin.py` for debugging.

- [ ] **Step 4: Migrate**

Run:
```bash
./venv/Scripts/python.exe manage.py makemigrations messaging
./venv/Scripts/python.exe manage.py migrate
```

- [ ] **Step 5: Run tests**

Run: `./venv/Scripts/python.exe manage.py test messaging.tests.test_models -v 2`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add messaging/
git commit -m "feat(messaging): add conversation and message models"
```

---

## Task 4: Permissions module

**Files:**
- Create: `messaging/permissions.py`
- Create: `messaging/tests/test_permissions.py`

- [ ] **Step 1: Write failing permission tests**

`messaging/tests/test_permissions.py` — cover at minimum:
- `user_can_manage_chat`: false by default; true when `can_manage_chat`; superuser bypass
- `employee_chat_enabled`: requires company switch + employee toggle + active + linked user
- `get_allowed_chat_contacts`: same-company only by default; cross-company when M2M set
- `can_manage_employees` alone does NOT grant `user_can_manage_chat`

Use `TestCase` with `Company`, `Employee`, `User`, `UserProfile`, `UserCompanyAccess` as needed (mirror `accounts/tests.py` patterns).

- [ ] **Step 2: Run tests — expect FAIL**

Run: `./venv/Scripts/python.exe manage.py test messaging.tests.test_permissions -v 2`

- [ ] **Step 3: Implement `messaging/permissions.py`**

Key functions per spec §7:
```python
def user_can_manage_chat(user) -> bool: ...
def employee_chat_enabled(employee) -> bool: ...
def user_can_use_employee_chat(user) -> bool: ...
def get_portal_employee(user): ...  # reuse portal pattern
def user_can_access_conversation(user, conversation) -> bool: ...
def get_allowed_chat_contacts(user): ...  # QuerySet[Employee]
def get_support_display_name(company) -> str: ...
def validate_group_participant_users(creator_user, user_ids: list[int]) -> list: ...
```

Import `MESSAGING_DEFAULT_SUPPORT_NAME` from `django.conf import settings`.
Import `user_can_access_company`, `get_accessible_companies` from `accounts.company_access`.

- [ ] **Step 4: Run tests — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add messaging/permissions.py messaging/tests/test_permissions.py
git commit -m "feat(messaging): add chat permission helpers"
```

---

## Task 5: Services module

**Files:**
- Create: `messaging/services.py`
- Create: `messaging/tests/test_services.py`

- [ ] **Step 1: Write failing service tests**

Cover:
- `get_or_create_admin_support_conversation` reuses existing thread
- `send_message` updates `conversation.last_message_at`
- `serialize_message_for_user` returns persona for employee viewer on admin_support
- `serialize_message_for_user` returns real name for admin viewer
- `soft_delete_message` sets `deleted_at`
- `unread_count_for_user` counts correctly after `mark_conversation_read`
- `validate_group_participant_users` rejects out-of-scope user

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement `messaging/services.py`**

Implement all functions listed in spec §9. Use `@transaction.atomic` on send/create operations.

`serialize_message_for_user(message, viewer)` returns dict:
```python
{
    'id': message.pk,
    'body': '[Message removed]' if message.deleted_at and not user_can_manage_chat(viewer) else message.body,
    'sender_display': ...,  # persona or real name
    'sender_user_id': message.sender_user_id,  # only include for admin/audit views
    'created_at': message.created_at.isoformat(),
    'is_deleted': bool(message.deleted_at),
}
```

- [ ] **Step 4: Run tests — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add messaging/services.py messaging/tests/test_services.py
git commit -m "feat(messaging): add conversation and message services"
```

---

## Task 6: Admin views, URLs, access decorator

**Files:**
- Create: `messaging/urls.py`, `messaging/views.py`, `messaging/decorators.py`
- Modify: `config/urls.py`
- Create: `messaging/tests/test_admin_views.py`

- [ ] **Step 1: Write failing view tests**

Test:
- Anonymous → redirect login
- User without `can_manage_chat` → 403 on `/messaging/`
- User with `can_manage_chat` → 200 on inbox
- POST send message in admin_support thread

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement decorator + views**

`messaging/decorators.py`:
```python
from functools import wraps
from django.core.exceptions import PermissionDenied
from .permissions import user_can_manage_chat

def chat_manager_required(view_func):
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if not user_can_manage_chat(request.user):
            raise PermissionDenied
        return view_func(request, *args, **kwargs)
    return wrapped
```

`messaging/views.py` — implement:
- `inbox` — list + search query param
- `compose` — GET form / POST create admin_support or group
- `thread` — GET messages + POST send; calls `mark_conversation_read`
- `archive_conversation` — POST only

`messaging/urls.py`:
```python
from django.urls import path
from . import views

app_name = 'messaging'

urlpatterns = [
    path('', views.inbox, name='inbox'),
    path('new/', views.compose, name='compose'),
    path('<int:pk>/', views.thread, name='thread'),
    path('<int:pk>/archive/', views.archive_conversation, name='archive'),
    path('audit/', views.audit_list, name='audit_list'),
    path('audit/<int:pk>/', views.audit_detail, name='audit_detail'),
    path('api/unread/', views.unread_api, name='unread_api'),
    path('api/thread/<int:pk>/', views.thread_api, name='thread_api'),
]
```

`config/urls.py`:
```python
path('messaging/', include('messaging.urls')),
```

Use `@login_required` + `@chat_manager_required` on admin views. Audit views use same gate.

- [ ] **Step 4: Run tests — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add messaging/ config/urls.py
git commit -m "feat(messaging): add admin chat views and URLs"
```

---

## Task 7: Portal views + middleware

**Files:**
- Create: `messaging/portal_views.py`
- Modify: `portal/urls.py`, `accounts/middleware.py`
- Create: `messaging/tests/test_portal_views.py`

- [ ] **Step 1: Write failing portal view tests**

- Employee without chat → 403 on `/portal/messages/`
- Enabled employee → 200 inbox
- Employee cannot open conversation they are not in

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement portal views**

`messaging/portal_views.py`:
- `portal_inbox`, `portal_compose`, `portal_thread`
- `portal_unread_api`, `portal_thread_api`
- Gate with `user_can_use_employee_chat`

`portal/urls.py` additions:
```python
from messaging import portal_views

urlpatterns += [
    path('messages/', portal_views.portal_inbox, name='messages_inbox'),
    path('messages/new/', portal_views.portal_compose, name='messages_compose'),
    path('messages/<int:pk>/', portal_views.portal_thread, name='messages_thread'),
    path('messages/api/unread/', portal_views.portal_unread_api, name='messages_unread_api'),
    path('messages/api/thread/<int:pk>/', portal_views.portal_thread_api, name='messages_thread_api'),
]
```

`accounts/middleware.py` — add `'/portal/messages/'` to allowed prefixes for employee-only users (same pattern as existing `/portal/` entries).

- [ ] **Step 4: Run tests — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add messaging/portal_views.py portal/urls.py accounts/middleware.py messaging/tests/test_portal_views.py
git commit -m "feat(messaging): add portal chat views and middleware allowance"
```

---

## Task 8: Admin templates

**Files:**
- Create: `templates/messaging/inbox.html`, `thread.html`, `compose.html`
- Create: `templates/messaging/partials/_message_bubble.html`
- Create: `templates/messaging/partials/_conversation_row.html`

- [ ] **Step 1: Create templates extending `base.html`**

Follow existing Stafforyx card/table patterns (see `templates/notifications/notification_list.html`).

`inbox.html`:
- Page header "Messages"
- Search input (GET `q`)
- List of conversations with unread badge, last message preview, timestamp
- Link to compose, link to audit (`{% url 'messaging:audit_list' %}`)

`thread.html`:
- Message list using `_message_bubble.html` (shows real sender names)
- POST form: `body` textarea + CSRF
- Soft-delete button per message (POST to delete endpoint or inline form)
- Poll script calling `thread_api` every `MESSAGING_POLL_INTERVAL_MS`

`compose.html`:
- Radio: Message employee (admin_support) vs Create official group
- Employee select (scoped to accessible companies, active, with user)
- Group: title + multi-select participants

- [ ] **Step 2: Manual smoke test**

Run server, log in as user with `can_manage_chat`, open `/messaging/`.

- [ ] **Step 3: Commit**

```bash
git add templates/messaging/
git commit -m "feat(messaging): add admin chat templates"
```

---

## Task 9: Portal templates

**Files:**
- Create: `templates/portal/messages/inbox.html`, `thread.html`, `compose.html`
- Reuse or duplicate `_message_bubble.html` with persona logic

- [ ] **Step 1: Create portal templates extending `portal/base.html`**

**Critical:** No monitoring disclaimer text anywhere.

`thread.html`:
- For `admin_support` messages, bubble shows persona only (via `sender_display` from service)
- POST reply form at bottom
- Poll `portal_thread_api`

`compose.html`:
- Direct vs Group tabs
- Participant picker populated only from `allowed_contacts` in view context

- [ ] **Step 2: Manual smoke test**

Log in as chat-enabled employee, open `/portal/messages/`.

- [ ] **Step 3: Commit**

```bash
git add templates/portal/messages/
git commit -m "feat(messaging): add portal chat templates"
```

---

## Task 10: Audit templates + views polish

**Files:**
- Create: `templates/messaging/audit_list.html`, `audit_detail.html`
- Modify: `messaging/views.py` (audit filters)

- [ ] **Step 1: Implement audit filters in `audit_list`**

GET params:
- `company` (id)
- `employee` (id)
- `q` (group title / message body search)
- `date_from`, `date_to`

Use `audit_conversations()` service; paginate 25 per page.

- [ ] **Step 2: Create audit templates**

`audit_list.html`: filter form + table (type, title, company, participants count, last activity).

`audit_detail.html`: participant list with employee names + admin usernames; full message history with **real sender** column, deleted indicator, timestamps.

- [ ] **Step 3: Write view test for audit access**

User without `can_manage_chat` → 403 on `/messaging/audit/`.

- [ ] **Step 4: Commit**

```bash
git add messaging/views.py templates/messaging/audit_list.html templates/messaging/audit_detail.html messaging/tests/
git commit -m "feat(messaging): add admin chat audit screen"
```

---

## Task 11: Context processor + navigation

**Files:**
- Create: `messaging/context_processors.py`
- Modify: `config/settings.py`, `templates/base.html`, `templates/portal/base.html`

- [ ] **Step 1: Implement context processor**

`messaging/context_processors.py`:
```python
from .permissions import user_can_manage_chat, user_can_use_employee_chat
from .services import unread_count_for_user

def messaging_context(request):
    if not request.user.is_authenticated:
        return {}
    can_manage = user_can_manage_chat(request.user)
    employee_chat = user_can_use_employee_chat(request.user)
    unread = 0
    if can_manage or employee_chat:
        unread = unread_count_for_user(request.user)
    return {
        'can_manage_chat_user': can_manage,
        'employee_chat_available': employee_chat,
        'messaging_unread_total': unread,
    }
```

Register in `config/settings.py` context_processors.

- [ ] **Step 2: Add sidebar nav items**

`templates/base.html` — under Admin / Management:
```html
{% if can_manage_chat_user %}
<li class="nav-item">
  <a href="{% url 'messaging:inbox' %}"
     class="nav-link {% if request.resolver_match.app_name == 'messaging' %}active{% endif %}">
    <i class="bi bi-chat-dots"></i>
    <span class="sidebar-text">Messages</span>
    <span id="sidebarMessagingBadge" class="sidebar-badge"
          {% if not messaging_unread_total %}style="display:none;"{% endif %}>{{ messaging_unread_total }}</span>
  </a>
</li>
{% endif %}
```

`templates/portal/base.html` — under My Portal (gate `employee_chat_available`):
```html
{% if employee_chat_available %}
<li class="nav-item">
  <a href="{% url 'portal:messages_inbox' %}"
     class="nav-link {% if request.resolver_match.url_name == 'messages_inbox' or request.resolver_match.url_name == 'messages_thread' %}active{% endif %}">
    <i class="bi bi-chat-dots"></i> Messages
    <span id="portalMessagingBadge" class="sidebar-badge"
          {% if not messaging_unread_total %}style="display:none;"{% endif %}>{{ messaging_unread_total }}</span>
  </a>
</li>
{% endif %}
```

- [ ] **Step 3: Add polling JS to base templates**

Mirror `notifications` poll block in `base.html`:
- Fetch `{% url 'messaging:unread_api' %}` every 15s when `can_manage_chat_user`
- Update `#sidebarMessagingBadge`

Same in `portal/base.html` for `portal:messages_unread_api` when `employee_chat_available`.

- [ ] **Step 4: Commit**

```bash
git add messaging/context_processors.py config/settings.py templates/base.html templates/portal/base.html
git commit -m "feat(messaging): add nav links, unread badges, and polling hooks"
```

---

## Task 12: Employee form + user form chat fields

**Files:**
- Modify: `employees/forms.py`, `templates/employees/employee_form.html`
- Modify: `accounts/forms.py` (or equivalent user form), `templates/accounts/user_form.html`

- [ ] **Step 1: Extend EmployeeForm**

Add `can_use_chat` and `allowed_chat_companies` fields. In `__init__`, filter `allowed_chat_companies` queryset to accessible companies excluding employee's own company. Show help text when `company.employee_chat_enabled` is false.

- [ ] **Step 2: Extend user management form**

Add `can_manage_chat` checkbox alongside other permission booleans.

- [ ] **Step 3: Update templates**

Add **Chat settings** fieldset on employee form.
Add **Chat** permission row on user form.

- [ ] **Step 4: Write form test**

Saving employee with `can_use_chat=True` and M2M persists correctly.

- [ ] **Step 5: Commit**

```bash
git add employees/ accounts/ templates/employees/ templates/accounts/
git commit -m "feat(messaging): expose chat settings on employee and user forms"
```

---

## Task 13: Polling API implementation

**Files:**
- Modify: `messaging/views.py`, `messaging/portal_views.py`
- Create: `messaging/tests/test_api.py`

- [ ] **Step 1: Write API tests**

- `unread_api` returns `total_unread` and `conversations` preview list
- `thread_api?after_id=N` returns only newer messages
- Opening thread marks read (decrements unread)

- [ ] **Step 2: Implement JSON views**

`unread_api` response shape:
```json
{
  "total_unread": 3,
  "conversations": [
    {"id": 1, "title": "...", "unread": 2, "url": "...", "preview": "...", "last_at": "..."}
  ]
}
```

`thread_api` response:
```json
{
  "messages": [ {"id": 5, "body": "...", "sender_display": "...", "created_at": "..."} ]
}
```

- [ ] **Step 3: Run tests — expect PASS**

- [ ] **Step 4: Commit**

```bash
git add messaging/views.py messaging/portal_views.py messaging/tests/test_api.py
git commit -m "feat(messaging): add unread and thread polling APIs"
```

---

## Task 14: Isolation + persona integration tests

**Files:**
- Create: `messaging/tests/test_isolation.py`, `messaging/tests/test_persona.py`

- [ ] **Step 1: Write isolation tests**

- Admin with access only to company A cannot load company B conversation (404/403)
- Audit list scoped to accessible companies

- [ ] **Step 2: Write persona tests**

- Employee GET thread API: admin message `sender_display == 'HR Support'` (default)
- Company override: `chat_support_display_name='Company Desk'` used
- Same message in audit detail includes real `sender_user` username

- [ ] **Step 3: Run full messaging test suite**

Run: `./venv/Scripts/python.exe manage.py test messaging -v 2`
Expected: all PASS

- [ ] **Step 4: Run project check**

Run: `./venv/Scripts/python.exe manage.py check`
Expected: no issues

- [ ] **Step 5: Commit**

```bash
git add messaging/tests/
git commit -m "test(messaging): add isolation and persona coverage"
```

---

## Task 15: Final QA + documentation cross-link

**Files:**
- Modify: `docs/superpowers/specs/2026-07-01-internal-chat-design.md` (add "Implemented" note when done — optional)

- [ ] **Step 1: Run full test suite**

Run: `./venv/Scripts/python.exe manage.py test -v 2`

- [ ] **Step 2: Manual QA per spec §18**

Walk through checklist in design spec.

- [ ] **Step 3: Verify non-regression**

- Sidebar highlighting on Dashboard, Employees, Payroll still works
- Employee portal-only middleware still blocks `/employees/` for portal users
- Notifications bell still polls

- [ ] **Step 4: Final commit if any fixes**

```bash
git commit -m "fix(messaging): address QA findings from internal chat Phase 1"
```

---

## Plan self-review (spec coverage)

| Spec requirement | Task |
|---|---|
| Dedicated messaging app | Task 1 |
| Text messages only | Task 3 (no attachment fields) |
| Admin persona | Task 5 `serialize_message_for_user`, Task 9 templates |
| Real sender audit | Task 3 `sender_user`, Task 10 audit |
| Private + group chat | Task 5 services, Task 6–7 views |
| Portal + admin inbox | Task 6–9 |
| Audit screen | Task 10 |
| Company master switch | Task 2 |
| Employee can_use_chat | Task 2, 12 |
| allowed_chat_companies | Task 2, 4, 12 |
| can_manage_chat | Task 2, 4, 12 |
| Polling only | Task 11, 13 |
| No review banner | Task 9 (explicit) |
| No attachments/GIFs/voice/reactions/read receipts/push/WS | Excluded from all tasks |
| Should-have: unread, recent, search, audit filters, soft delete | Tasks 5, 6, 10, 11, 13 |

**Gaps:** None identified.

---

## Execution handoff

**Plan complete and saved to `docs/superpowers/plans/2026-07-01-internal-chat.md`.**

**Two execution options:**

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration.

2. **Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
