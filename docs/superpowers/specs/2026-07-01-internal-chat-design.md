# Internal Chat (Messaging) — Design Spec

- **Date:** 2026-07-01
- **App:** Stafforyx HR (Django 6.0.5; SQLite local, PostgreSQL production via env)
- **Status:** Approved design (pre-implementation)

## 1. Goal

Add a company-scoped internal messaging system inside the existing Django app so
admins/HR can privately chat with employees, employees can reply from the portal,
and enabled employees can direct-message or group-chat with permitted contacts —
while preserving Stafforyx company isolation, storing all messages in PostgreSQL
(or SQLite locally), and giving authorized admins a silent audit trail without any
employee-visible monitoring notice.

## 2. Requirements summary

### Must Have (Phase 1)

| Requirement | Design decision |
|---|---|
| Admin privately chats with any employee | `admin_support` conversation; admin inbox at `/messaging/` |
| Employee replies from portal | Portal inbox at `/portal/messages/` |
| Employee private chat with allowed employees | `direct` conversations; contact list from permission service |
| Employee create/join group conversations | `group` conversations; invite validation server-side |
| Admin audit screen (participants + history) | `/messaging/audit/` gated by `can_manage_chat` |
| No visible review notice/banner | No copy about monitoring on portal or chat UI |
| Chat permissions from admin/employee side | Company master switch + per-employee toggle + cross-company M2M |
| Default employee chat restricted | `can_use_chat=False`, `employee_chat_enabled=False` |
| Cross-company only when admin allows | `Employee.allowed_chat_companies` M2M |
| Messages in PostgreSQL | Standard Django ORM; prod uses `DB_ENGINE=postgresql` env |
| Inside existing Django app | New `messaging` app; no separate service |
| Company isolation preserved | `company` FK on conversations; existing access helpers |

### Should Have (Phase 1)

| Requirement | Design decision |
|---|---|
| Unread message count | `ConversationReadState` + polling APIs + sidebar badges |
| Recent conversations list | Inbox sorted by `last_message_at` (denormalized or annotated) |
| Basic message search | `body__icontains` within accessible conversations |
| Admin audit filters | company, employee, group title, date range |
| Soft delete/archive | `Message.deleted_at`; `Conversation.is_archived` |

### Could Have (not Phase 1)

Read receipts, message reactions, typing indicator.

### Won't Have (Phase 1)

GIF messages, voice messages, picture/file attachments, push notifications,
WebSocket real-time chat.

### Phase 2 (deferred)

Department/location chat restrictions within the same company.

## 3. Architecture

### Approach

**Dedicated `messaging` Django app** (recommended and approved). Mirrors existing
patterns in `notifications` and `announcements`: models, services, function-based
views, Bootstrap templates, HTTP polling.

Rejected alternatives:

- Extending `notifications` — wrong abstraction (one-way alerts, not threads).
- Splitting into multiple apps — unnecessary complexity for Phase 1.

### High-level components

```
messaging/
  models.py           Conversation, ConversationParticipant, Message, ConversationReadState
  constants.py        conversation types, roles, settings keys
  permissions.py      can_manage_chat, employee chat gates, contact list, access checks
  services.py         send message, get/create conversations, unread counts, search, archive
  views.py            admin inbox, thread, compose, audit, polling API
  portal_views.py     portal inbox, thread, compose, polling API
  urls.py             /messaging/*
  admin.py            read-only model registration (optional)
  context_processors.py  unread badge counts for base.html / portal/base.html
  tests/              permission matrix, persona display, isolation, audit

companies/models.py   + employee_chat_enabled, chat_support_display_name
employees/models.py   + can_use_chat, allowed_chat_companies (M2M)
accounts/models.py    + can_manage_chat on UserProfile
config/settings.py    + messaging app, MESSAGING_DEFAULT_SUPPORT_NAME, context processor
config/urls.py        + path('messaging/', ...)
portal/urls.py        + portal message routes (or include messaging portal urls)
templates/messaging/  admin UI
templates/portal/messages/  portal UI (or templates/messaging/portal/)
```

### Real-time strategy

**HTTP polling only** (Phase 1). Mirror `notifications:unread_api`:

- Admin: `GET /messaging/api/unread/` every **15s** from `templates/base.html`
- Portal: `GET /portal/messages/api/unread/` every **15s** from `templates/portal/base.html`
- Open thread: `GET /messaging/api/thread/<id>/` (or portal equivalent) every **15s**

No Django Channels, no WebSockets, no push notifications.

## 4. Admin persona vs audit sender

### Employee-facing display (Option B — approved)

When an employee views an `admin_support` conversation:

- Sender label = company persona name (`Company.chat_support_display_name` if set,
  else global default **"HR Support"** from `settings.MESSAGING_DEFAULT_SUPPORT_NAME`).
- Employee never sees the real admin Django username or full name.

When an employee views `direct` or `group` conversations:

- Sender label = participant's real display name (employee full name).

### Admin-facing display

- Admin inbox and thread views show real sender identity for all message types.
- Audit screen always shows `Message.sender_user` (username + full name if available).

### Storage rule

Every `Message` row stores `sender_user` (FK → `User`, required). Persona is
**never** stored on the message; it is computed at render time from the
conversation type and company settings.

## 5. Data model changes (existing apps)

### `Company` (`companies/models.py`)

| Field | Type | Default | Notes |
|---|---|---|---|
| `employee_chat_enabled` | BooleanField | `False` | Master switch; when off, no employee portal chat for this company |
| `chat_support_display_name` | CharField(100) blank | `""` | Persona override for admin_support threads; blank → global default |

### `Employee` (`employees/models.py`)

| Field | Type | Default | Notes |
|---|---|---|---|
| `can_use_chat` | BooleanField | `False` | Per-employee toggle; HR must explicitly enable |
| `allowed_chat_companies` | M2M → `Company` | empty | Cross-company chat targets admin explicitly allows |

M2M `related_name='chat_enabled_employees'` on Company (or similar). Only companies
the admin user can access should appear as choices on the employee form.

### `UserProfile` (`accounts/models.py`)

| Field | Type | Default | Notes |
|---|---|---|---|
| `can_manage_chat` | BooleanField | `False` | Admin chat inbox, official groups, employee messaging, audit screen |

Superusers always bypass this check (same pattern as `has_module_access`).

### `settings.py`

```python
MESSAGING_DEFAULT_SUPPORT_NAME = "HR Support"
MESSAGING_POLL_INTERVAL_MS = 15000
```

## 6. New models (`messaging/models.py`)

### `Conversation`

| Field | Type | Notes |
|---|---|---|
| `company` | FK Company | Owning company; scopes isolation |
| `conversation_type` | CharField | `direct`, `admin_support`, `group` |
| `title` | CharField(150) blank | Required for groups; optional otherwise |
| `created_by` | FK User | Creator |
| `is_archived` | Boolean default False | Soft archive (conversation-level) |
| `archived_at` | DateTimeField null | |
| `archived_by` | FK User null | |
| `last_message_at` | DateTimeField null | Denormalized for inbox sort |
| `created_at` / `updated_at` | auto | |

**Indexes:** `(company, last_message_at)`, `(conversation_type, company)`.

**Uniqueness:** One active `admin_support` conversation per `(company, employee_user)`.
Enforced in service layer when admin opens chat with an employee.

### `ConversationParticipant`

| Field | Type | Notes |
|---|---|---|
| `conversation` | FK Conversation | `related_name='participants'` |
| `user` | FK User | Participant identity |
| `employee` | FK Employee null | Denormalized when participant is an employee |
| `role` | CharField | `member`, `group_creator`, `admin` |
| `joined_at` | DateTimeField auto | |
| `left_at` | DateTimeField null | Soft leave |

`unique_together = (conversation, user)` for active membership. Reactivation clears
`left_at` if user re-added.

### `Message`

| Field | Type | Notes |
|---|---|---|
| `conversation` | FK Conversation | `related_name='messages'` |
| `sender_user` | FK User | **Always** the real sender (audit) |
| `body` | TextField | Plain text only; max length 5000 (validated) |
| `created_at` | DateTimeField auto | |
| `deleted_at` | DateTimeField null | Soft delete |
| `deleted_by` | FK User null | |

**Indexes:** `(conversation, created_at)`, `(conversation, -created_at)` for pagination.

No attachments, reactions, or read-receipt fields in Phase 1.

### `ConversationReadState`

| Field | Type | Notes |
|---|---|---|
| `conversation` | FK Conversation | |
| `user` | FK User | |
| `last_read_at` | DateTimeField | Updated when user opens thread or polls with read marker |

`unique_together = (conversation, user)`.

**Unread definition:** messages in conversation where `created_at > last_read_at`
and `sender_user != current_user` and `deleted_at is null`.

## 7. Permission logic (`messaging/permissions.py`)

### Helper functions

```python
def user_can_manage_chat(user) -> bool
def employee_chat_enabled(employee) -> bool
def user_can_use_employee_chat(user) -> bool
def user_can_access_conversation(user, conversation) -> bool
def get_allowed_chat_contacts(user) -> QuerySet[Employee]
def validate_group_participants(creator_user, participant_user_ids) -> list[User]
def get_support_display_name(company) -> str
```

### `user_can_manage_chat(user)`

True when `user.is_superuser` OR `user.stafforyx_profile.can_manage_chat` (and
profile is active).

### `employee_chat_enabled(employee)`

True when ALL of:

1. `employee.company.employee_chat_enabled`
2. `employee.can_use_chat`
3. `employee.status == 'active'`
4. `employee.user` is not null (linked portal account)

### `user_can_use_employee_chat(user)`

Resolves portal employee via `portal.views._get_portal_employee` pattern; returns
`employee_chat_enabled(employee)`.

### Allowed contact list (`get_allowed_chat_contacts`)

For employee `E` with home company `C`:

1. **Same company:** active employees in `C` where `can_use_chat=True`,
   `company.employee_chat_enabled=True`, have linked `user`, exclude self.
2. **Cross-company:** active employees in companies from
   `E.allowed_chat_companies.all()` with the same chat-enabled conditions.

No department or attendance-location filtering in Phase 1.

### Group invite validation

When any user creates or updates a group:

- Creator must have chat access (admin: `can_manage_chat`; employee: `user_can_use_employee_chat`).
- Every invited `user_id` must belong to an allowed contact (employee path) or be
  an accessible employee in admin's companies (admin path).
- Reject with validation error if any participant is out of scope.
- All participants' home companies must be either the conversation `company` or
  in the creating employee's `allowed_chat_companies` (for employee-created groups).

### Conversation access

User must be an active participant (`left_at is null`) OR be on audit view with
`can_manage_chat` and `user_can_access_company` for the conversation's company.

All list/detail querysets pass through `filter_queryset_by_user_companies` on
`company` field.

## 8. Conversation types and flows

### `admin_support`

- **Created by:** admin with `can_manage_chat` messaging an employee.
- **Participants:** target employee's `user` + creating admin's `user` (additional
  admins with `can_manage_chat` may be added when they send — auto-join on first send).
- **Reuse:** if an active `admin_support` conversation already exists for
  `(company, employee_user)`, open it instead of creating a duplicate.
- **Employee UI:** all admin messages show persona name only.
- **Admin UI:** shows real sender per message.

### `direct`

- **Created by:** enabled employee or admin with `can_manage_chat`.
- **Participants:** exactly two users.
- **Reuse:** one active direct thread per unordered pair within scope (service finds existing).
- **Display:** real names both sides.

### `group`

- **Created by:** admin (`can_manage_chat`) for official groups, or enabled employee.
- **Participants:** 3+ users (creator + at least 2 others); minimum 2 for direct only.
- **Title:** required; shown in inbox.
- **Employee-created:** invite list validated against `get_allowed_chat_contacts`.
- **Admin-created:** participants must be employees in admin's accessible companies
  with chat enabled (or other admins with `can_manage_chat`).

## 9. Services (`messaging/services.py`)

Core operations (all permission-checked):

| Function | Purpose |
|---|---|
| `get_or_create_admin_support_conversation(admin_user, employee)` | Reuse or create admin_support thread |
| `get_or_create_direct_conversation(user_a, user_b)` | Reuse or create direct thread |
| `create_group_conversation(creator, title, participant_users, company)` | New group |
| `send_message(conversation, sender, body)` | Create message; update `last_message_at` |
| `soft_delete_message(message, actor)` | Set `deleted_at` / `deleted_by` |
| `archive_conversation(conversation, actor)` | Set `is_archived` |
| `mark_conversation_read(conversation, user)` | Upsert `ConversationReadState` |
| `unread_count_for_user(user)` | Total unread across conversations |
| `unread_count_for_conversation(conversation, user)` | Per-thread unread |
| `inbox_for_user(user, *, search=None, archived=False)` | Recent conversations list |
| `messages_for_conversation(conversation, user, *, after_id=None)` | Paginated messages |
| `search_messages(user, query, filters)` | Basic body search for audit + inbox |
| `audit_conversations(user, filters)` | Admin audit queryset with filters |
| `serialize_message_for_user(message, viewer_user)` | Applies persona vs real name rules |

Deleted messages render as *"[Message removed]"* to participants; audit retains
body for `can_manage_chat` users (or show body with "deleted" badge — pick one:
**audit shows full body with deleted indicator**).

## 10. URLs and views

### Admin (`/messaging/`)

| URL | View | Gate |
|---|---|---|
| `/messaging/` | `inbox` | `can_manage_chat` |
| `/messaging/new/` | `compose` | `can_manage_chat` |
| `/messaging/<int:pk>/` | `thread` | participant or `can_manage_chat` + company access |
| `/messaging/<int:pk>/archive/` | POST archive | participant admin or creator |
| `/messaging/audit/` | `audit_list` | `can_manage_chat` |
| `/messaging/audit/<int:pk>/` | `audit_detail` | `can_manage_chat` + company access |
| `/messaging/api/unread/` | JSON unread summary | `can_manage_chat` |
| `/messaging/api/thread/<int:pk>/` | JSON new messages | conversation access |

### Portal (`/portal/messages/`)

| URL | View | Gate |
|---|---|---|
| `/portal/messages/` | `portal_inbox` | `user_can_use_employee_chat` |
| `/portal/messages/new/` | `portal_compose` | `user_can_use_employee_chat` |
| `/portal/messages/<int:pk>/` | `portal_thread` | participant |
| `/portal/messages/api/unread/` | JSON unread | `user_can_use_employee_chat` |
| `/portal/messages/api/thread/<int:pk>/` | JSON new messages | participant |

Register portal routes in `portal/urls.py` (import from `messaging.portal_views`).

### Middleware compatibility

`EmployeePortalOnlyMiddleware` must allow `/portal/messages/` paths for
employee-only users (add prefix to allowed list in `accounts/middleware.py`).

## 11. UI integration

### Admin sidebar (`templates/base.html`)

- New nav item **Messages** under **Admin / Management** (or new **Communication** section).
- Visible when `can_manage_chat_user` context flag is true.
- Unread badge on nav link (from context processor).
- Active state: `request.resolver_match.app_name == 'messaging'`.

### Admin user dropdown

No change required (chat is sidebar, not dropdown).

### Portal sidebar (`templates/portal/base.html`)

- New nav item **Messages** under **My Portal** or **Requests**.
- Visible when `employee_chat_available` context flag is true.
- Unread badge on nav link.

### Employee form (`templates/employees/employee_form.html`)

New section **Chat settings** (visible to users with `can_manage_employees`):

- Read-only indicator if `company.employee_chat_enabled` is false.
- Checkbox `can_use_chat`.
- Multi-select `allowed_chat_companies` (filtered to accessible companies ≠ employee's company).

### Company settings

Add chat fields to Django admin company edit (`/admin/companies/company/`) **or**
a section on an existing company settings page if one exists. Minimum for Phase 1:
fields editable via Django admin company form **and** exposed on employee form's
company read-only note. Prefer also adding to `companies` admin fieldsets.

### User management form (`accounts/user_form.html`)

- Checkbox `can_manage_chat` in permissions section (alongside other `can_manage_*` flags).

### Templates (new)

- `templates/messaging/inbox.html` — conversation list + search box
- `templates/messaging/thread.html` — message list + send form + poll JS
- `templates/messaging/compose.html` — start admin_support / official group
- `templates/messaging/audit_list.html` — filters + conversation table
- `templates/messaging/audit_detail.html` — participants + full history with real senders
- `templates/portal/messages/inbox.html`
- `templates/portal/messages/thread.html`
- `templates/portal/messages/compose.html`

Shared partial: `templates/messaging/partials/_message_bubble.html` (persona vs name).

**No banner** text such as "messages may be monitored" anywhere in portal templates.

## 12. Context processors

### `messaging/context_processors.py`

Inject into templates:

| Variable | Condition |
|---|---|
| `can_manage_chat_user` | `user_can_manage_chat(request.user)` |
| `employee_chat_available` | `user_can_use_employee_chat(request.user)` |
| `messaging_unread_total` | unread count (0 if not applicable) |

Add to `TEMPLATES['OPTIONS']['context_processors']` in `config/settings.py`.

Skip heavy queries on auth pages (mirror `notifications` processor pattern).

## 13. Security and isolation

- All conversation queries filter by accessible companies.
- Portal employees cannot enumerate conversations outside their participation.
- Employee compose participant picker is server-rendered from `get_allowed_chat_contacts` only.
- POST endpoints re-validate permissions (never trust client participant lists).
- CSRF on all forms; `@login_required` on all views.
- Rate limiting: not required Phase 1 (optional `body` length + max messages/minute later).
- `EmployeePortalOnlyMiddleware` updated for portal message paths.
- No changes to `.env`, `db.sqlite3`, or production-only settings files.
- Migrations created during implementation (not in this spec commit).

## 14. PostgreSQL notes

- Use `TextField` for message body (no `BinaryField`).
- Add DB indexes listed above; compatible with SQLite for local dev tests.
- No full-text search extension required Phase 1 (`icontains` is sufficient).
- Production deployment sets `DB_ENGINE=django.db.backends.postgresql` via existing env pattern.

## 15. Testing strategy

### `messaging/tests/test_permissions.py`

- Default-off: employee without `can_use_chat` cannot access portal messages.
- Company master switch off blocks employee chat even if `can_use_chat=True`.
- Cross-company contact only when in `allowed_chat_companies`.
- `can_manage_chat` required for admin inbox; superuser bypass.
- `can_manage_employees` alone does **not** grant chat access.

### `messaging/tests/test_persona.py`

- Employee view of `admin_support` shows persona name, not admin username.
- Admin/audit view shows `sender_user` identity.

### `messaging/tests/test_conversations.py`

- Reuse existing `admin_support` thread per employee.
- Direct pair reuse.
- Group invite rejects out-of-scope participant.
- Soft delete and archive behavior.

### `messaging/tests/test_isolation.py`

- HR admin in company A cannot read company B conversations.
- `filter_queryset_by_user_companies` respected in audit list.

### `messaging/tests/test_api.py`

- Unread API returns counts; marking read on thread view decreases count.
- Poll endpoint returns only new messages after `after_id`.

## 16. Explicit non-goals (Phase 1)

- WebSockets / Django Channels / SSE
- Push notifications (mobile or browser)
- File/image/voice/GIF attachments
- Read receipts, reactions, typing indicators
- Department or attendance-location chat restrictions
- Email notifications for new messages
- End-to-end encryption
- Employee-visible monitoring disclaimers
- Changes to license middleware or attendance/portal clock flows

## 17. Implementation sequence (overview)

1. Scaffold `messaging` app + constants
2. Add fields to `Company`, `Employee`, `UserProfile` + migrations
3. Add messaging models + migrations
4. Permissions module + tests
5. Services module + tests
6. Admin views, URLs, templates
7. Portal views, URLs, templates
8. Polling APIs + JS
9. Navigation + context processors + forms
10. Audit screen
11. Full test pass + manual QA checklist

Detailed bite-sized tasks: `docs/superpowers/plans/2026-07-01-internal-chat.md`.

## 18. Manual QA checklist (post-implementation)

- [ ] Company with chat disabled: employee sees no Messages nav item.
- [ ] Employee with `can_use_chat=False`: no portal messages access.
- [ ] Employee with chat enabled: can open inbox, DM same-company contact.
- [ ] Cross-company DM works only when target company is in `allowed_chat_companies`.
- [ ] Admin with `can_manage_chat`: can message employee; employee sees "HR Support".
- [ ] Admin audit shows real admin username on same messages.
- [ ] No monitoring banner on portal chat screens.
- [ ] Group create rejects invalid participant (403/validation error).
- [ ] Unread badge updates within poll interval.
- [ ] Archive soft-hides conversation; delete soft-hides message.
- [ ] Other sidebar modules (payroll, attendance, etc.) still work and highlight correctly.
