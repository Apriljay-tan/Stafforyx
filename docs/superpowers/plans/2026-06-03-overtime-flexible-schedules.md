# Overtime Requests + Flexible Schedules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-employee overtime policy, employee-portal overtime requests with HR approval, and flexible-schedule attendance — without rewriting the attendance engine or changing fixed-shift behavior.

**Architecture:** A new `overtime` Django app owns `OvertimeRequest`, the `payable_overtime_minutes` helper, and the auto-create signal. The attendance engine keeps detecting *raw* overtime; an additive, flag-guarded branch in `compute_attendance` handles flexible schedules. Payroll consumes the payable helper instead of reading raw `overtime_minutes`. Employee request views live in `portal`; company-scoped HR review views live in `overtime`.

**Tech Stack:** Django 6.0.5, SQLite (dev), Bootstrap templates, Django `TestCase`.

**Spec:** `docs/superpowers/specs/2026-06-03-overtime-flexible-schedules-design.md`

---

## File Structure

**New files (overtime app):**
- `overtime/__init__.py` — empty package marker
- `overtime/apps.py` — `OvertimeConfig`, registers signals in `ready()`
- `overtime/models.py` — `OvertimeRequest`
- `overtime/services.py` — `payable_overtime_minutes`, `build_overtime_approval_index`
- `overtime/signals.py` — `post_save` auto-create for `management_review`
- `overtime/admin.py` — `OvertimeRequestAdmin`
- `overtime/views.py` — `manage_overtime`, `manage_overtime_detail` (company-scoped)
- `overtime/urls.py` — HR routes (`app_name = 'overtime'`)
- `overtime/tests.py` — helper, signal, payroll, portal, HR, access tests
- `overtime/migrations/__init__.py`
- `templates/overtime/manage_overtime.html` — HR list (extends `base.html`)
- `templates/overtime/manage_overtime_detail.html` — HR detail/approve (extends `base.html`)
- `templates/portal/overtime_list.html` — employee list + today's schedule + request button (extends `portal/base.html`)
- `templates/portal/overtime_new.html` — employee request form (extends `portal/base.html`)

**Modified files:**
- `config/settings.py:60` — add `"overtime"` to `INSTALLED_APPS`
- `config/urls.py:29` — `path('overtime/', include('overtime.urls'))`
- `employees/models.py` — 6 new `Employee` fields
- `employees/admin.py:60` — add "Overtime & Schedule" fieldset
- `attendance/services.py` — additive flexible branch inside the scheduled-workday block
- `attendance/tests.py` — new flexible + fixed-regression test classes
- `payroll/services.py` — build approval index; use `payable_overtime_minutes`
- `payroll/tests.py` — payroll OT-gating tests
- `portal/forms.py` — `PortalOvertimeRequestForm`
- `portal/views.py` — `portal_overtime_list`, `portal_overtime_new`
- `portal/urls.py` — employee overtime routes
- `templates/portal/base.html` — nav link to overtime (optional, see Task 14)

---

## Phase 1 — Models, App Wiring, Admin

### Task 1: Create the overtime app skeleton + register it

**Files:**
- Create: `overtime/__init__.py`, `overtime/migrations/__init__.py`, `overtime/apps.py`
- Modify: `config/settings.py:60`

- [ ] **Step 1: Create package markers**

`overtime/__init__.py` — empty file.
`overtime/migrations/__init__.py` — empty file.

- [ ] **Step 2: Create `overtime/apps.py`**

```python
from django.apps import AppConfig


class OvertimeConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'overtime'
    verbose_name = 'Overtime'

    def ready(self):
        # Import signal handlers so they are registered.
        from . import signals  # noqa: F401
```

- [ ] **Step 3: Register the app in `config/settings.py`**

Modify the `INSTALLED_APPS` list — add `"overtime",` immediately after `"holidays",` (line 60):

```python
    "portal",
    "holidays",
    "overtime",
]
```

- [ ] **Step 4: Add a temporary empty signals module so `ready()` imports cleanly**

Create `overtime/signals.py` with a placeholder (replaced in Task 7):

```python
# Signal handlers registered in OvertimeConfig.ready().
# Auto-create logic added in Phase 3.
```

- [ ] **Step 5: Verify Django loads the app**

Run: `python manage.py check`
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 6: Commit**

```bash
git add overtime/__init__.py overtime/migrations/__init__.py overtime/apps.py overtime/signals.py config/settings.py
git commit -m "feat(overtime): scaffold overtime app and register it"
```

---

### Task 2: Add overtime + flexible-schedule fields to Employee

**Files:**
- Modify: `employees/models.py:36-83` (inside `Employee`)
- Modify: `employees/admin.py:60`

- [ ] **Step 1: Add the `OVERTIME_POLICY_CHOICES` constant + fields to `Employee`**

In `employees/models.py`, inside `class Employee`, add the choices constant alongside the other choice lists (after `PAY_BASIS_CHOICES`, around line 53):

```python
    OVERTIME_POLICY_CHOICES = [
        ('not_allowed',       'Not Allowed'),
        ('automatic',         'Automatic'),
        ('request_required',  'Request Required'),
        ('management_review', 'Management Review'),
    ]
```

Then add these fields after `work_schedule` (after line 119, before `created_at`):

```python
    overtime_policy = models.CharField(
        max_length=20, choices=OVERTIME_POLICY_CHOICES, default='not_allowed',
        help_text='Controls how this employee\'s overtime is paid by payroll.',
    )
    flexible_schedule_enabled = models.BooleanField(
        default=False,
        help_text='If on, attendance uses required daily hours instead of a fixed start/end.',
    )
    required_daily_hours = models.DecimalField(
        max_digits=4, decimal_places=2, default=8.00,
        help_text='Hours a flexible employee must complete per day.',
    )
    allowed_clock_in_from = models.TimeField(
        null=True, blank=True,
        help_text='Earliest allowed clock-in for flexible employees.',
    )
    allowed_clock_in_until = models.TimeField(
        null=True, blank=True,
        help_text='Latest allowed clock-in for flexible employees.',
    )
    default_break_minutes = models.PositiveIntegerField(
        default=60,
        help_text='Break minutes assumed for flexible computation when not recorded.',
    )
```

- [ ] **Step 2: Expose the fields in the admin**

In `employees/admin.py`, add a new fieldset to `EmployeeAdmin.fieldsets`, inserted after the `'Employment Details'` fieldset (after line 48):

```python
        ('Overtime & Schedule', {
            'fields': (
                'work_schedule', 'overtime_policy',
                'flexible_schedule_enabled', 'required_daily_hours',
                'allowed_clock_in_from', 'allowed_clock_in_until',
                'default_break_minutes',
            )
        }),
```

- [ ] **Step 3: Generate the migration**

Run: `python manage.py makemigrations employees`
Expected: a new migration `employees/migrations/000X_employee_overtime_policy_and_more.py` adding 6 fields.

- [ ] **Step 4: CHECKPOINT — ask before applying migrations**

Per project rules, **stop and ask the user** to confirm before running `migrate`. Show the generated migration filename. Only after approval:

Run: `python manage.py migrate employees`
Expected: `Applying employees.000X... OK`

- [ ] **Step 5: Verify**

Run: `python manage.py check`
Expected: no issues.

- [ ] **Step 6: Commit**

```bash
git add employees/models.py employees/admin.py employees/migrations/
git commit -m "feat(employees): add overtime policy + flexible schedule fields"
```

---

### Task 3: Create the OvertimeRequest model

**Files:**
- Create: `overtime/models.py`
- Create: `overtime/admin.py`

- [ ] **Step 1: Write `overtime/models.py`**

```python
from django.contrib.auth.models import User
from django.db import models

from companies.models import Company
from employees.models import Employee


class OvertimeRequest(models.Model):
    STATUS_CHOICES = [
        ('pending',       'Pending'),
        ('approved',      'Approved'),
        ('rejected',      'Rejected'),
        ('auto_approved', 'Auto Approved'),
    ]
    SOURCE_CHOICES = [
        ('employee', 'Employee'),
        ('detected', 'Detected'),
        ('hr',       'HR'),
    ]

    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name='overtime_requests'
    )
    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name='overtime_requests'
    )
    date = models.DateField()
    requested_hours = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    approved_hours = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        help_text='Hours actually approved. Blank until reviewed; '
                  'falls back to requested hours on approval.',
    )
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='employee')
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='reviewed_overtime_requests',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    manager_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date', 'employee']
        unique_together = ('employee', 'date')
        indexes = [
            models.Index(fields=['company', 'status']),
            models.Index(fields=['employee', 'date']),
        ]

    def __str__(self):
        return f'{self.employee} — {self.date} ({self.get_status_display()})'
```

- [ ] **Step 2: Write `overtime/admin.py`**

```python
from django.contrib import admin

from .models import OvertimeRequest


@admin.register(OvertimeRequest)
class OvertimeRequestAdmin(admin.ModelAdmin):
    list_display = (
        'employee', 'company', 'date', 'requested_hours',
        'approved_hours', 'status', 'source', 'reviewed_by', 'reviewed_at',
    )
    list_filter = ('company', 'status', 'source')
    search_fields = (
        'employee__first_name', 'employee__last_name',
        'employee__employee_id', 'company__name',
    )
    readonly_fields = ('created_at', 'updated_at')
    date_hierarchy = 'date'
```

- [ ] **Step 3: Generate the migration**

Run: `python manage.py makemigrations overtime`
Expected: `overtime/migrations/0001_initial.py` creating `OvertimeRequest`.

- [ ] **Step 4: CHECKPOINT — ask before applying migrations**

Stop and ask the user to confirm. After approval:

Run: `python manage.py migrate overtime`
Expected: `Applying overtime.0001_initial... OK`

- [ ] **Step 5: Verify**

Run: `python manage.py check`
Expected: no issues.

- [ ] **Step 6: Commit**

```bash
git add overtime/models.py overtime/admin.py overtime/migrations/0001_initial.py
git commit -m "feat(overtime): add OvertimeRequest model + admin"
```

---

## Phase 2 — Attendance Flexible Branch (additive, guarded)

### Task 4: Add flexible-schedule branch to compute_attendance

**Files:**
- Modify: `attendance/services.py:84-133` (scheduled-workday block only)
- Test: `attendance/tests.py` (new classes)

> The fixed-shift code is preserved verbatim — only indented one level deeper under a new
> `else:` so the flag-off path is unchanged.

- [ ] **Step 1: Write the failing tests**

Append to `attendance/tests.py`:

```python
class FlexibleScheduleAttendanceTests(TestCase):
    """Flexible employees: no late from start; under/overtime vs required_daily_hours."""

    def setUp(self):
        self.company = _make_company()
        # Mon-Fri schedule used only for workday/rest-day resolution.
        self.schedule = _make_schedule(
            self.company,
            start_time=datetime.time(8, 0),
            end_time=datetime.time(17, 0),
        )

    def _flex_employee(self, required_hours='8.00', break_minutes=60):
        emp = _make_employee(self.company, self.schedule)
        emp.flexible_schedule_enabled = True
        emp.required_daily_hours = Decimal(required_hours)
        emp.default_break_minutes = break_minutes
        emp.save(update_fields=[
            'flexible_schedule_enabled', 'required_daily_hours', 'default_break_minutes',
        ])
        return emp

    def test_flexible_not_late_when_starting_later(self):
        emp = self._flex_employee()
        # Starts 10:00, works to 19:00, 60 min break = 8.0h worked.
        rec = _make_record(
            emp, time_in=datetime.time(10, 0), time_out=datetime.time(19, 0),
        )
        compute_attendance(rec)
        rec.refresh_from_db()
        self.assertEqual(rec.late_minutes, 0)
        self.assertEqual(rec.undertime_minutes, 0)
        self.assertEqual(rec.overtime_minutes, 0)
        self.assertEqual(rec.computed_status, 'present')

    def test_flexible_undertime_when_below_required(self):
        emp = self._flex_employee()
        # 09:00-15:00, 60 min break = 5.0h worked → 3h (180 min) undertime.
        rec = _make_record(
            emp, time_in=datetime.time(9, 0), time_out=datetime.time(15, 0),
        )
        compute_attendance(rec)
        rec.refresh_from_db()
        self.assertEqual(rec.late_minutes, 0)
        self.assertEqual(rec.undertime_minutes, 180)
        self.assertEqual(rec.overtime_minutes, 0)
        self.assertEqual(rec.computed_status, 'undertime')

    def test_flexible_overtime_when_above_required(self):
        emp = self._flex_employee()
        # 08:00-19:00, 60 min break = 10.0h worked → 2h (120 min) overtime.
        rec = _make_record(
            emp, time_in=datetime.time(8, 0), time_out=datetime.time(19, 0),
        )
        compute_attendance(rec)
        rec.refresh_from_db()
        self.assertEqual(rec.overtime_minutes, 120)
        self.assertEqual(rec.undertime_minutes, 0)
        self.assertEqual(rec.computed_status, 'overtime')


class FixedShiftRegressionTests(TestCase):
    """Guards: fixed-shift behavior must be unchanged by the flexible branch."""

    def setUp(self):
        self.company = _make_company()
        # 2 PM - 10 PM shift, grace 15, break 60.
        self.schedule = _make_schedule(
            self.company,
            start_time=datetime.time(14, 0),
            end_time=datetime.time(22, 0),
        )

    def test_fixed_shift_late_undertime_overtime(self):
        emp = _make_employee(self.company, self.schedule)
        self.assertFalse(emp.flexible_schedule_enabled)
        # Clock in 14:30 (15 min late after grace), out 22:00.
        rec = _make_record(
            emp, time_in=datetime.time(14, 30), time_out=datetime.time(22, 0),
        )
        compute_attendance(rec)
        rec.refresh_from_db()
        self.assertEqual(rec.late_minutes, 15)
        # Expected = 8h shift - 1h break = 7h; worked 22:00-14:30-60 = 6.5h → 30 min undertime.
        self.assertEqual(rec.undertime_minutes, 30)
        self.assertEqual(rec.overtime_minutes, 0)
        self.assertEqual(rec.computed_status, 'late')

    def test_fixed_shift_overtime(self):
        emp = _make_employee(self.company, self.schedule)
        # 14:00 - 23:30: worked 9.5h - 1h break = 8.5h; OT after 22:00 = 90 min.
        rec = _make_record(
            emp, time_in=datetime.time(14, 0), time_out=datetime.time(23, 30),
        )
        compute_attendance(rec)
        rec.refresh_from_db()
        self.assertEqual(rec.overtime_minutes, 90)
        self.assertEqual(rec.computed_status, 'overtime')
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python manage.py test attendance.tests.FlexibleScheduleAttendanceTests -v 2`
Expected: FAIL — flexible employee currently computes late/undertime via fixed logic
(e.g. `test_flexible_not_late_when_starting_later` shows non-zero late_minutes).

- [ ] **Step 3: Add the flexible branch in `compute_attendance`**

In `attendance/services.py`, replace the scheduled-workday `else:` block (currently lines
84-133, starting `else:` / `# ── Scheduled workday`) with the version below. The fixed-shift
math is unchanged — it now lives under `else:` after the flexible guard:

```python
    else:
        # ── Scheduled workday ─────────────────────────────────────────────────
        if not record.time_in:
            computed = 'absent'
        else:
            employee = record.employee
            if getattr(employee, 'flexible_schedule_enabled', False):
                # ── Flexible schedule (additive, guarded) ─────────────────────
                # Never late for starting later within the allowed window.
                late_min = 0
                if not record.time_out:
                    computed = 'incomplete'
                else:
                    time_in_min = _to_min(record.time_in)
                    time_out_min = _to_min(record.time_out)
                    if shift.get('is_overnight', False) and time_out_min <= time_in_min:
                        time_out_min += 24 * 60
                    break_min = (
                        record.break_minutes
                        if record.break_minutes is not None
                        else (employee.default_break_minutes or 0)
                    )
                    total_work_min = max(0, time_out_min - time_in_min - break_min)
                    required_min = int(
                        (Decimal(str(employee.required_daily_hours or 0)) * _60)
                        .to_integral_value(rounding=ROUND_HALF_UP)
                    )
                    undertime_min = max(0, required_min - total_work_min)
                    overtime_min = max(0, total_work_min - required_min)
                    if overtime_min > 0:
                        undertime_min = 0
                        computed = 'overtime'
                    elif undertime_min > 0:
                        computed = 'undertime'
                    else:
                        computed = 'present'
            else:
                # ── Fixed shift (UNCHANGED) ───────────────────────────────────
                sched_start_min = _to_min(shift['start_time'])
                grace = shift['grace_minutes'] or 0
                time_in_min = _to_min(record.time_in)
                late_min = max(0, time_in_min - (sched_start_min + grace))

                if not record.time_out:
                    computed = 'incomplete'
                else:
                    time_out_min = _to_min(record.time_out)
                    sched_end_min = _to_min(shift['end_time'])
                    is_overnight = shift.get('is_overnight', False)

                    # Overnight: adjust both ends to be continuous minutes from midnight
                    if is_overnight:
                        if sched_end_min <= sched_start_min:
                            sched_end_min += 24 * 60
                        if time_out_min <= time_in_min:
                            time_out_min += 24 * 60

                    break_min = (
                        record.break_minutes
                        if record.break_minutes is not None
                        else shift['break_minutes']
                    )
                    total_work_min = max(0, time_out_min - time_in_min - break_min)

                    # Expected minutes = scheduled span minus break
                    expected_min = max(0, sched_end_min - sched_start_min - shift['break_minutes'])
                    undertime_min = max(0, expected_min - total_work_min)

                    ot_start_min = sched_end_min + (shift['overtime_after_minutes'] or 0)
                    overtime_min = max(0, time_out_min - ot_start_min)

                    # Overtime cancels undertime
                    if overtime_min > 0:
                        undertime_min = 0

                    if overtime_min > 0:
                        computed = 'overtime'
                    elif undertime_min > 0:
                        computed = 'undertime'
                    elif late_min > 0:
                        computed = 'late'
                    else:
                        computed = 'present'
```

- [ ] **Step 4: Run the new tests — verify they pass**

Run: `python manage.py test attendance.tests.FlexibleScheduleAttendanceTests attendance.tests.FixedShiftRegressionTests -v 2`
Expected: PASS (5 tests).

- [ ] **Step 5: Run the full attendance suite — verify no regressions**

Run: `python manage.py test attendance -v 1`
Expected: OK (all existing tests still pass).

- [ ] **Step 6: Commit**

```bash
git add attendance/services.py attendance/tests.py
git commit -m "feat(attendance): add flag-guarded flexible schedule branch"
```

---

## Phase 3 — Payable Helper + Auto-Create Signal

### Task 5: Implement payable_overtime_minutes + approval index

**Files:**
- Create: `overtime/services.py`
- Test: `overtime/tests.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `overtime/tests.py`:

```python
import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from companies.models import Company
from employees.models import Employee
from .models import OvertimeRequest
from .services import build_overtime_approval_index, payable_overtime_minutes

_DATE = datetime.date(2026, 5, 26)


def _company():
    return Company.objects.create(name='OT Co')


_counter = 0


def _employee(company, policy='not_allowed'):
    global _counter
    _counter += 1
    return Employee.objects.create(
        company=company,
        employee_id=f'OT{_counter:03d}',
        first_name='Over',
        last_name='Time',
        date_hired=datetime.date(2024, 1, 1),
        status='active',
        overtime_policy=policy,
    )


class PayableOvertimeHelperTests(TestCase):
    def setUp(self):
        self.company = _company()

    def _index(self, employees):
        return build_overtime_approval_index(self.company, employees, _DATE, _DATE)

    def test_automatic_pays_detected(self):
        emp = _employee(self.company, 'automatic')
        idx = self._index([emp])
        self.assertEqual(payable_overtime_minutes(emp, _DATE, 120, idx), 120)

    def test_request_required_zero_without_approval(self):
        emp = _employee(self.company, 'request_required')
        idx = self._index([emp])
        self.assertEqual(payable_overtime_minutes(emp, _DATE, 120, idx), 0)

    def test_request_required_pays_min_detected_approved(self):
        emp = _employee(self.company, 'request_required')
        OvertimeRequest.objects.create(
            company=self.company, employee=emp, date=_DATE,
            requested_hours=Decimal('2.00'), approved_hours=Decimal('1.50'),
            status='approved', source='employee',
        )
        idx = self._index([emp])
        # detected 120 min, approved 1.5h = 90 min → min = 90.
        self.assertEqual(payable_overtime_minutes(emp, _DATE, 120, idx), 90)

    def test_management_review_zero_until_approved(self):
        emp = _employee(self.company, 'management_review')
        OvertimeRequest.objects.create(
            company=self.company, employee=emp, date=_DATE,
            requested_hours=Decimal('2.00'), status='pending', source='detected',
        )
        idx = self._index([emp])
        self.assertEqual(payable_overtime_minutes(emp, _DATE, 120, idx), 0)

    def test_not_allowed_pays_only_with_override(self):
        emp = _employee(self.company, 'not_allowed')
        idx = self._index([emp])
        self.assertEqual(payable_overtime_minutes(emp, _DATE, 120, idx), 0)
        OvertimeRequest.objects.create(
            company=self.company, employee=emp, date=_DATE,
            requested_hours=Decimal('2.00'), status='approved', source='hr',
        )
        idx = self._index([emp])
        self.assertEqual(payable_overtime_minutes(emp, _DATE, 120, idx), 120)

    def test_approved_hours_falls_back_to_requested(self):
        emp = _employee(self.company, 'request_required')
        OvertimeRequest.objects.create(
            company=self.company, employee=emp, date=_DATE,
            requested_hours=Decimal('1.00'), approved_hours=None,
            status='approved', source='employee',
        )
        idx = self._index([emp])
        # approved_hours None → fall back to requested 1.0h = 60 min.
        self.assertEqual(payable_overtime_minutes(emp, _DATE, 120, idx), 60)
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `python manage.py test overtime.tests.PayableOvertimeHelperTests -v 2`
Expected: FAIL — `cannot import name 'payable_overtime_minutes'`.

- [ ] **Step 3: Write `overtime/services.py`**

```python
"""
Overtime payment resolution.

payable_overtime_minutes(...) maps raw *detected* overtime (from the attendance
engine) to the minutes payroll should actually pay, based on the employee's
overtime policy and any approved OvertimeRequest. The attendance engine is never
modified by this module — it only consumes its output.
"""

from decimal import Decimal, ROUND_HALF_UP

_60 = Decimal(60)


def build_overtime_approval_index(company, employees, start_date, end_date):
    """
    Return {(employee_id, date): OvertimeRequest} for approved/auto_approved
    requests in [start_date, end_date]. One query, used by payroll.
    """
    from .models import OvertimeRequest

    qs = OvertimeRequest.objects.filter(
        company=company,
        employee__in=employees,
        date__gte=start_date,
        date__lte=end_date,
        status__in=['approved', 'auto_approved'],
    )
    return {(o.employee_id, o.date): o for o in qs}


def _approved_minutes(request):
    """Approved hours → minutes; approved_hours falls back to requested_hours."""
    hours = request.approved_hours
    if hours is None:
        hours = request.requested_hours
    return int((Decimal(str(hours or 0)) * _60).to_integral_value(rounding=ROUND_HALF_UP))


def payable_overtime_minutes(employee, date, detected_min, approval_index):
    """
    Resolve payable overtime minutes for one employee/date.

    - automatic          → detected.
    - request_required   → 0, or min(detected, approved) if an approved request exists.
    - management_review  → 0, or min(detected, approved) once approved.
    - not_allowed        → 0, unless an approved (HR override) request exists → capped.
    """
    detected_min = detected_min or 0
    policy = getattr(employee, 'overtime_policy', 'not_allowed')

    if policy == 'automatic':
        return detected_min

    request = approval_index.get((employee.id, date))
    if request is None:
        return 0
    return min(detected_min, _approved_minutes(request))
```

- [ ] **Step 4: Run tests — verify they pass**

Run: `python manage.py test overtime.tests.PayableOvertimeHelperTests -v 2`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add overtime/services.py overtime/tests.py
git commit -m "feat(overtime): add payable_overtime_minutes helper + approval index"
```

---

### Task 6: Auto-create pending request for management_review detected OT

**Files:**
- Modify: `overtime/signals.py`
- Test: `overtime/tests.py` (new class)

- [ ] **Step 1: Write the failing tests**

Append to `overtime/tests.py`:

```python
class AutoCreateSignalTests(TestCase):
    def setUp(self):
        self.company = _company()

    def _attendance_record(self, emp, overtime_minutes):
        from attendance.models import AttendanceRecord
        return AttendanceRecord.objects.create(
            company=self.company, employee=emp, date=_DATE,
            time_in=datetime.time(14, 0), time_out=datetime.time(23, 0),
            overtime_minutes=overtime_minutes, status='present',
        )

    def test_management_review_detected_ot_creates_pending(self):
        emp = _employee(self.company, 'management_review')
        self._attendance_record(emp, 120)
        req = OvertimeRequest.objects.get(employee=emp, date=_DATE)
        self.assertEqual(req.status, 'pending')
        self.assertEqual(req.source, 'detected')
        self.assertEqual(req.requested_hours, Decimal('2.00'))

    def test_no_request_when_zero_overtime(self):
        emp = _employee(self.company, 'management_review')
        self._attendance_record(emp, 0)
        self.assertFalse(OvertimeRequest.objects.filter(employee=emp, date=_DATE).exists())

    def test_no_request_for_non_management_review_policy(self):
        for policy in ['not_allowed', 'automatic', 'request_required']:
            emp = _employee(self.company, policy)
            self._attendance_record(emp, 120)
            self.assertFalse(
                OvertimeRequest.objects.filter(employee=emp, date=_DATE).exists(),
                f'unexpected request created for policy={policy}',
            )

    def test_idempotent_updates_pending_requested_hours(self):
        emp = _employee(self.company, 'management_review')
        rec = self._attendance_record(emp, 120)
        rec.overtime_minutes = 180
        rec.save(update_fields=['overtime_minutes'])
        reqs = OvertimeRequest.objects.filter(employee=emp, date=_DATE)
        self.assertEqual(reqs.count(), 1)
        self.assertEqual(reqs.first().requested_hours, Decimal('3.00'))

    def test_does_not_override_reviewed_request(self):
        emp = _employee(self.company, 'management_review')
        rec = self._attendance_record(emp, 120)
        req = OvertimeRequest.objects.get(employee=emp, date=_DATE)
        req.status = 'approved'
        req.approved_hours = Decimal('2.00')
        req.save(update_fields=['status', 'approved_hours'])
        rec.overtime_minutes = 240
        rec.save(update_fields=['overtime_minutes'])
        req.refresh_from_db()
        self.assertEqual(req.status, 'approved')
        self.assertEqual(req.requested_hours, Decimal('2.00'))  # unchanged
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `python manage.py test overtime.tests.AutoCreateSignalTests -v 2`
Expected: FAIL — no request rows created (placeholder signals.py does nothing).

- [ ] **Step 3: Replace `overtime/signals.py` with the handler**

```python
"""
Auto-create a pending OvertimeRequest when overtime is detected for an employee
whose policy is `management_review`, so HR sees it in the review queue.

Registered in OvertimeConfig.ready(). Idempotent via the (employee, date) unique
constraint; never overrides an already-reviewed request.
"""

from decimal import Decimal, ROUND_HALF_UP

from django.db.models.signals import post_save
from django.dispatch import receiver

from attendance.models import AttendanceRecord

_Q2 = Decimal('0.01')


@receiver(post_save, sender=AttendanceRecord, dispatch_uid='overtime_auto_create')
def auto_create_management_review_overtime(sender, instance, **kwargs):
    employee = instance.employee
    if getattr(employee, 'overtime_policy', None) != 'management_review':
        return

    detected = instance.overtime_minutes or 0
    if detected <= 0:
        return

    from .models import OvertimeRequest

    hours = (Decimal(detected) / Decimal(60)).quantize(_Q2, rounding=ROUND_HALF_UP)
    obj, created = OvertimeRequest.objects.get_or_create(
        employee=employee,
        date=instance.date,
        defaults=dict(
            company=instance.company,
            requested_hours=hours,
            reason='Auto-detected overtime',
            status='pending',
            source='detected',
        ),
    )
    # Keep a still-pending detected row in sync with recomputed attendance.
    if (
        not created
        and obj.status == 'pending'
        and obj.source == 'detected'
        and obj.requested_hours != hours
    ):
        obj.requested_hours = hours
        obj.save(update_fields=['requested_hours', 'updated_at'])
```

- [ ] **Step 4: Run tests — verify they pass**

Run: `python manage.py test overtime.tests.AutoCreateSignalTests -v 2`
Expected: PASS (5 tests).

- [ ] **Step 5: Run the attendance suite — confirm signal didn't break compute**

Run: `python manage.py test attendance -v 1`
Expected: OK.

- [ ] **Step 6: Commit**

```bash
git add overtime/signals.py overtime/tests.py
git commit -m "feat(overtime): auto-create pending request for detected management-review OT"
```

---

## Phase 4 — Payroll Integration

### Task 7: Pay only payable overtime in payroll

**Files:**
- Modify: `payroll/services.py:42-47` (imports), `:160-296` (`_calc_employee_payroll`), `:300-379` (`generate_payroll_for_period`)
- Test: `payroll/tests.py` (new class)

- [ ] **Step 1: Write the failing tests**

Append to `payroll/tests.py` (imports at top of the file if not present:
`import datetime`, `from decimal import Decimal`, `from companies.models import Company`,
`from employees.models import Employee`, `from attendance.models import AttendanceRecord, WorkSchedule`,
`from .models import PayrollPeriod, PayrollRecord`, `from .services import generate_payroll_for_period`,
`from overtime.models import OvertimeRequest`):

```python
class PayrollOvertimeGatingTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='Pay Co')
        # Mon-Fri 8-17 schedule.
        self.schedule = WorkSchedule.objects.create(
            company=self.company, name='Std',
            start_time=datetime.time(8, 0), end_time=datetime.time(17, 0),
            grace_minutes=15, break_minutes=60, required_hours=Decimal('8.00'),
        )
        # Single-day period on a Monday.
        self.day = datetime.date(2026, 5, 25)  # Monday
        self.period = PayrollPeriod.objects.create(
            company=self.company, name='May D1',
            start_date=self.day, end_date=self.day,
        )

    def _emp(self, policy):
        emp = Employee.objects.create(
            company=self.company, employee_id=f'P-{policy}',
            first_name='Pay', last_name='Roll',
            date_hired=datetime.date(2024, 1, 1), status='active',
            basic_salary=Decimal('26000.00'),  # daily_rate=1000, hourly=125
            overtime_policy=policy,
        )
        emp.work_schedule = self.schedule
        emp.save(update_fields=['work_schedule'])
        return emp

    def _attendance(self, emp, overtime_minutes=120):
        return AttendanceRecord.objects.create(
            company=self.company, employee=emp, date=self.day,
            time_in=datetime.time(8, 0), time_out=datetime.time(19, 0),
            overtime_minutes=overtime_minutes, status='present',
        )

    def _record(self, emp):
        generate_payroll_for_period(self.period)
        return PayrollRecord.objects.get(payroll_period=self.period, employee=emp)

    def test_automatic_overtime_is_paid(self):
        emp = self._emp('automatic')
        self._attendance(emp, 120)
        rec = self._record(emp)
        self.assertEqual(rec.overtime_minutes, 120)
        # 2h * 125 * 1.25 = 312.50
        self.assertEqual(rec.overtime_pay, Decimal('312.50'))

    def test_request_required_not_paid_until_approved(self):
        emp = self._emp('request_required')
        self._attendance(emp, 120)
        rec = self._record(emp)
        self.assertEqual(rec.overtime_minutes, 0)
        self.assertEqual(rec.overtime_pay, Decimal('0.00'))

    def test_request_required_paid_after_approval(self):
        emp = self._emp('request_required')
        self._attendance(emp, 120)
        OvertimeRequest.objects.create(
            company=self.company, employee=emp, date=self.day,
            requested_hours=Decimal('2.00'), approved_hours=Decimal('2.00'),
            status='approved', source='employee',
        )
        rec = self._record(emp)
        self.assertEqual(rec.overtime_minutes, 120)
        self.assertEqual(rec.overtime_pay, Decimal('312.50'))
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `python manage.py test payroll.tests.PayrollOvertimeGatingTests -v 2`
Expected: FAIL — `request_required` currently pays raw detected OT (overtime_pay 312.50, expected 0).

- [ ] **Step 3: Import the helper in `payroll/services.py`**

After the existing import block (after line 47, `from .models import PayrollRecord`), add:

```python
from overtime.services import build_overtime_approval_index, payable_overtime_minutes
```

- [ ] **Step 4: Thread the approval index through `_calc_employee_payroll`**

Change the function signature (line 160-161) from:

```python
def _calc_employee_payroll(emp, scheduled_dates, paid_leave_dates, unpaid_leave_dates,
                           att_by_date, holiday_resolver):
```

to:

```python
def _calc_employee_payroll(emp, scheduled_dates, paid_leave_dates, unpaid_leave_dates,
                           att_by_date, holiday_resolver, approval_index):
```

In the **normal pass** (currently line 202-203), replace:

```python
            overtime_min += att.overtime_minutes or 0
```

with:

```python
            overtime_min += payable_overtime_minutes(
                emp, date, att.overtime_minutes or 0, approval_index
            )
```

In the **holiday-worked pass** (currently line 227), replace:

```python
            overtime_min += att.overtime_minutes or 0
```

with:

```python
            overtime_min += payable_overtime_minutes(
                emp, date, att.overtime_minutes or 0, approval_index
            )
```

- [ ] **Step 5: Build the approval index in `generate_payroll_for_period` and pass it**

After the attendance map is built (after line 328, `att_map = _build_attendance_map(...)`), add:

```python
    approval_index = build_overtime_approval_index(
        period.company, emp_list, start_date, end_date
    )
```

Then update the `_calc_employee_payroll(...)` call (line 348-355) to pass it as the final arg:

```python
        components = _calc_employee_payroll(
            emp,
            scheduled_sets.get(emp.pk, set()),
            paid_map.get(emp.pk, set()),
            unpaid_map.get(emp.pk, set()),
            att_map.get(emp.pk, {}),
            _holiday_resolver,
            approval_index,
        )
```

- [ ] **Step 6: Run tests — verify they pass**

Run: `python manage.py test payroll.tests.PayrollOvertimeGatingTests -v 2`
Expected: PASS (3 tests).

- [ ] **Step 7: Run the full payroll suite — confirm holiday logic untouched**

Run: `python manage.py test payroll -v 1`
Expected: OK (all existing payroll/holiday tests pass).

- [ ] **Step 8: Commit**

```bash
git add payroll/services.py payroll/tests.py
git commit -m "feat(payroll): pay only payable (policy-resolved) overtime"
```

---

## Phase 5 — Employee Portal

### Task 8: Employee overtime request form

**Files:**
- Modify: `portal/forms.py`

- [ ] **Step 1: Add `PortalOvertimeRequestForm` to `portal/forms.py`**

Add the import near the top (after `from leaves.models import ...`):

```python
from overtime.models import OvertimeRequest
```

Add the form class at the end of the file:

```python
class PortalOvertimeRequestForm(forms.ModelForm):
    class Meta:
        model = OvertimeRequest
        fields = ['date', 'requested_hours', 'reason']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'requested_hours': forms.NumberInput(attrs={'step': '0.25', 'min': '0.25'}),
            'reason': forms.Textarea(attrs={'rows': 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrap(self)

    def clean_requested_hours(self):
        hours = self.cleaned_data.get('requested_hours')
        if hours is None or hours <= 0:
            raise forms.ValidationError('Requested hours must be greater than zero.')
        return hours
```

- [ ] **Step 2: Verify import resolves**

Run: `python manage.py check`
Expected: no issues.

- [ ] **Step 3: Commit**

```bash
git add portal/forms.py
git commit -m "feat(portal): add overtime request form"
```

---

### Task 9: Employee overtime views + URLs

**Files:**
- Modify: `portal/views.py`, `portal/urls.py`
- Test: `overtime/tests.py` (portal class)

- [ ] **Step 1: Write the failing tests**

Append to `overtime/tests.py`:

```python
from django.urls import reverse


class PortalOvertimeViewTests(TestCase):
    def setUp(self):
        self.company = _company()
        self.user = User.objects.create_user('emp1', password='pw')
        self.emp = _employee(self.company, 'request_required')
        self.emp.user = self.user
        self.emp.save(update_fields=['user'])
        self.client.force_login(self.user)

    def test_list_page_loads(self):
        resp = self.client.get(reverse('portal:overtime_list'))
        self.assertEqual(resp.status_code, 200)

    def test_employee_can_submit_request(self):
        resp = self.client.post(reverse('portal:overtime_new'), {
            'date': _DATE.isoformat(),
            'requested_hours': '2.00',
            'reason': 'Project deadline',
        })
        self.assertEqual(resp.status_code, 302)
        req = OvertimeRequest.objects.get(employee=self.emp, date=_DATE)
        self.assertEqual(req.status, 'pending')
        self.assertEqual(req.source, 'employee')
        self.assertEqual(req.company, self.company)

    def test_duplicate_date_is_rejected_gracefully(self):
        OvertimeRequest.objects.create(
            company=self.company, employee=self.emp, date=_DATE,
            requested_hours=Decimal('1.00'), status='pending', source='employee',
        )
        resp = self.client.post(reverse('portal:overtime_new'), {
            'date': _DATE.isoformat(),
            'requested_hours': '2.00',
            'reason': 'second attempt',
        })
        # No second row, no 500.
        self.assertEqual(OvertimeRequest.objects.filter(employee=self.emp, date=_DATE).count(), 1)
        self.assertIn(resp.status_code, (200, 302))
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `python manage.py test overtime.tests.PortalOvertimeViewTests -v 2`
Expected: FAIL — `Reverse for 'overtime_list' not found`.

- [ ] **Step 3: Add the views to `portal/views.py`**

Add imports near the top (with the other model imports):

```python
import datetime
from attendance.schedule_services import resolve_expected_shift
from overtime.models import OvertimeRequest
from .forms import PortalOvertimeRequestForm
```

Add the views (place after the attendance section, before the HR section):

```python
# ── Portal: Overtime ──────────────────────────────────────────────────────────

@login_required
def portal_overtime_list(request):
    employee, fallback = _require_portal_employee(request)
    if fallback:
        return fallback

    today = datetime.date.today()
    shift = resolve_expected_shift(employee, today)
    requests = (
        OvertimeRequest.objects
        .filter(employee=employee)
        .order_by('-date')
    )
    can_request = employee.overtime_policy != 'not_allowed'

    return render(request, 'portal/overtime_list.html', {
        'employee': employee,
        'requests': requests,
        'today': today,
        'shift': shift,
        'can_request': can_request,
        'policy_display': employee.get_overtime_policy_display(),
    })


@login_required
def portal_overtime_new(request):
    employee, fallback = _require_portal_employee(request)
    if fallback:
        return fallback

    if employee.overtime_policy == 'not_allowed':
        messages.error(request, 'Overtime requests are not allowed for your account.')
        return redirect('portal:overtime_list')

    if request.method == 'POST':
        form = PortalOvertimeRequestForm(request.POST)
        if form.is_valid():
            date = form.cleaned_data['date']
            if OvertimeRequest.objects.filter(employee=employee, date=date).exists():
                messages.warning(
                    request,
                    'You already have an overtime request for that date.',
                )
                return redirect('portal:overtime_list')
            ot = form.save(commit=False)
            ot.employee = employee
            ot.company = employee.company
            ot.status = 'pending'
            ot.source = 'employee'
            ot.save()
            messages.success(request, 'Overtime request submitted. Waiting for approval.')
            return redirect('portal:overtime_list')
    else:
        form = PortalOvertimeRequestForm()

    return render(request, 'portal/overtime_new.html', {
        'employee': employee,
        'form': form,
    })
```

- [ ] **Step 4: Add URL routes to `portal/urls.py`**

Add to `urlpatterns`, in the "Employee self-service" group (after the `attendance`/`time-clock` lines):

```python
    path('overtime/', views.portal_overtime_list, name='overtime_list'),
    path('overtime/new/', views.portal_overtime_new, name='overtime_new'),
```

- [ ] **Step 5: Create `templates/portal/overtime_new.html`**

```html
{% extends 'portal/base.html' %}

{% block title %}Request Overtime{% endblock %}
{% block page_title %}Request Overtime{% endblock %}

{% block content %}
<div class="page-header mb-3">
  <h1>Request Overtime</h1>
  <p>Submit an overtime request for management approval.</p>
</div>

<div class="card">
  <div class="card-header">
    <i class="bi bi-clock-history me-1"></i>Overtime Details
  </div>
  <div class="card-body">
    <form method="post" class="row g-3">
      {% csrf_token %}
      {% if form.non_field_errors %}
      <div class="col-12"><div class="alert alert-danger">{{ form.non_field_errors }}</div></div>
      {% endif %}
      <div class="col-12 col-md-4">
        <label class="form-label">{{ form.date.label }}</label>
        {{ form.date }}
        {{ form.date.errors }}
      </div>
      <div class="col-12 col-md-4">
        <label class="form-label">Requested Hours</label>
        {{ form.requested_hours }}
        {{ form.requested_hours.errors }}
      </div>
      <div class="col-12">
        <label class="form-label">{{ form.reason.label }}</label>
        {{ form.reason }}
        {{ form.reason.errors }}
      </div>
      <div class="col-12 d-flex justify-content-end gap-2">
        <a href="{% url 'portal:overtime_list' %}" class="btn btn-outline-secondary">Cancel</a>
        <button type="submit" class="btn btn-primary">
          <i class="bi bi-send me-1"></i>Submit Request
        </button>
      </div>
    </form>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 6: Create `templates/portal/overtime_list.html`**

```html
{% extends 'portal/base.html' %}

{% block title %}My Overtime{% endblock %}
{% block page_title %}My Overtime{% endblock %}

{% block content %}
<div class="page-header mb-3 d-flex justify-content-between align-items-center flex-wrap gap-2">
  <div>
    <h1>Overtime</h1>
    <p>Today's schedule, your overtime policy, and request history.</p>
  </div>
  {% if can_request %}
  <a href="{% url 'portal:overtime_new' %}" class="btn btn-primary btn-sm">
    <i class="bi bi-plus-lg me-1"></i>Request Overtime
  </a>
  {% endif %}
</div>

<div class="card mb-3">
  <div class="card-header"><i class="bi bi-calendar-day me-1"></i>Today — {{ today|date:"M d, Y" }}</div>
  <div class="card-body">
    <p class="mb-1">
      <strong>Schedule:</strong>
      {% if shift.scheduled %}
        {% if employee.flexible_schedule_enabled %}
          Flexible — {{ employee.required_daily_hours }} required hours
          {% if employee.allowed_clock_in_from %}
            (window {{ employee.allowed_clock_in_from|time:"g:i A" }}–{{ employee.allowed_clock_in_until|time:"g:i A" }})
          {% endif %}
        {% else %}
          {{ shift.start_time|time:"g:i A" }} – {{ shift.end_time|time:"g:i A" }}
        {% endif %}
      {% elif shift.is_rest_day %}
        Rest day
      {% else %}
        No schedule today
      {% endif %}
    </p>
    <p class="mb-0"><strong>Overtime policy:</strong> {{ policy_display }}</p>
  </div>
</div>

<div class="card">
  <div class="card-header d-flex justify-content-between align-items-center">
    <span><i class="bi bi-clock-history me-1"></i>Request History</span>
    <span class="badge bg-primary rounded-pill">{{ requests.count }}</span>
  </div>
  <div class="table-responsive">
    <table class="table table-hover mb-0 align-middle" style="font-size:.875rem;">
      <thead class="table-light">
        <tr>
          <th class="ps-3">Date</th>
          <th>Requested</th>
          <th>Approved</th>
          <th>Status</th>
          <th class="pe-3">Reason</th>
        </tr>
      </thead>
      <tbody>
        {% for r in requests %}
        <tr>
          <td class="ps-3">{{ r.date|date:"M d, Y" }}</td>
          <td>{{ r.requested_hours }}h</td>
          <td>{% if r.approved_hours is not None %}{{ r.approved_hours }}h{% else %}—{% endif %}</td>
          <td>
            {% if r.status == 'approved' or r.status == 'auto_approved' %}<span class="badge text-bg-success">{{ r.get_status_display }}</span>
            {% elif r.status == 'rejected' %}<span class="badge text-bg-danger">Rejected</span>
            {% else %}<span class="badge text-bg-warning">Pending</span>{% endif %}
          </td>
          <td class="pe-3 text-muted">{{ r.reason|truncatechars:60 }}</td>
        </tr>
        {% empty %}
        <tr><td colspan="5" class="text-center py-5 text-muted">No overtime requests yet.</td></tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 7: Run tests — verify they pass**

Run: `python manage.py test overtime.tests.PortalOvertimeViewTests -v 2`
Expected: PASS (3 tests).

- [ ] **Step 8: Commit**

```bash
git add portal/views.py portal/urls.py templates/portal/overtime_list.html templates/portal/overtime_new.html overtime/tests.py
git commit -m "feat(portal): employee overtime request + status views"
```

---

## Phase 6 — HR / Admin Review

### Task 10: Company-scoped HR overtime list + approve/reject

**Files:**
- Create: `overtime/views.py`, `overtime/urls.py`
- Create: `templates/overtime/manage_overtime.html`, `templates/overtime/manage_overtime_detail.html`
- Modify: `config/urls.py:29`
- Test: `overtime/tests.py` (HR + access classes)

- [ ] **Step 1: Write the failing tests**

Append to `overtime/tests.py`:

```python
from accounts.models import UserCompanyAccess


class ManageOvertimeAccessTests(TestCase):
    def setUp(self):
        self.company = _company()
        self.other = Company.objects.create(name='Other Co')
        self.emp = _employee(self.company, 'request_required')
        self.req = OvertimeRequest.objects.create(
            company=self.company, employee=self.emp, date=_DATE,
            requested_hours=Decimal('2.00'), status='pending', source='employee',
        )

    def test_plain_employee_cannot_access_hr_pages(self):
        user = User.objects.create_user('plain', password='pw')
        self.client.force_login(user)
        resp = self.client.get(reverse('overtime:manage_overtime'))
        self.assertEqual(resp.status_code, 403)

    def test_hr_sees_only_in_scope_companies(self):
        hr = User.objects.create_user('hr', password='pw')
        from accounts.models import UserProfile
        profile, _ = UserProfile.objects.get_or_create(user=hr)
        profile.can_manage_employees = True
        profile.save()
        UserCompanyAccess.objects.create(user=hr, company=self.company, is_active=True)
        self.client.force_login(hr)

        # In-scope request visible.
        resp = self.client.get(reverse('overtime:manage_overtime'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.emp.last_name)

        # Out-of-scope request not visible.
        other_emp = Employee.objects.create(
            company=self.other, employee_id='X1', first_name='Out', last_name='Scope',
            date_hired=datetime.date(2024, 1, 1), status='active',
        )
        OvertimeRequest.objects.create(
            company=self.other, employee=other_emp, date=_DATE,
            requested_hours=Decimal('1.00'), status='pending', source='employee',
        )
        resp = self.client.get(reverse('overtime:manage_overtime'))
        self.assertNotContains(resp, 'Scope')

    def test_superuser_can_approve_and_sets_review_fields(self):
        su = User.objects.create_superuser('root', 'root@x.com', 'pw')
        self.client.force_login(su)
        resp = self.client.post(
            reverse('overtime:manage_overtime_detail', args=[self.req.pk]),
            {'action': 'approve', 'approved_hours': '1.50', 'manager_note': 'ok'},
        )
        self.assertEqual(resp.status_code, 302)
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, 'approved')
        self.assertEqual(self.req.approved_hours, Decimal('1.50'))
        self.assertEqual(self.req.reviewed_by, su)
        self.assertIsNotNone(self.req.reviewed_at)

    def test_approve_defaults_approved_hours_to_requested(self):
        su = User.objects.create_superuser('root2', 'root2@x.com', 'pw')
        self.client.force_login(su)
        self.client.post(
            reverse('overtime:manage_overtime_detail', args=[self.req.pk]),
            {'action': 'approve', 'approved_hours': '', 'manager_note': ''},
        )
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, 'approved')
        self.assertEqual(self.req.approved_hours, Decimal('2.00'))
```

> If `UserProfile` field/relation names differ, mirror exactly what `portal.manage_incidents`
> checks: `request.user.stafforyx_profile.can_manage_employees`. Adjust the test setup to set
> whatever attribute that resolves to.

- [ ] **Step 2: Run tests — verify they fail**

Run: `python manage.py test overtime.tests.ManageOvertimeAccessTests -v 2`
Expected: FAIL — `Reverse for 'manage_overtime' not found`.

- [ ] **Step 3: Write `overtime/views.py`**

```python
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.company_access import (
    filter_queryset_by_user_companies,
    user_can_access_company,
)

from .models import OvertimeRequest


def _require_hr(request):
    profile = getattr(request.user, 'stafforyx_profile', None)
    is_hr = request.user.is_superuser or (profile and profile.can_manage_employees)
    if not is_hr:
        raise PermissionDenied


@login_required
def manage_overtime(request):
    _require_hr(request)

    requests = filter_queryset_by_user_companies(
        OvertimeRequest.objects.select_related('employee', 'company').order_by('-date'),
        request.user,
    )

    status_filter = request.GET.get('status', '')
    date_filter = request.GET.get('date', '')
    employee_filter = request.GET.get('employee', '')

    if status_filter:
        requests = requests.filter(status=status_filter)
    if date_filter:
        requests = requests.filter(date=date_filter)
    if employee_filter:
        requests = requests.filter(employee_id=employee_filter)

    return render(request, 'overtime/manage_overtime.html', {
        'requests': requests,
        'status_filter': status_filter,
        'date_filter': date_filter,
        'employee_filter': employee_filter,
        'status_choices': OvertimeRequest.STATUS_CHOICES,
    })


@login_required
def manage_overtime_detail(request, pk):
    _require_hr(request)

    ot = get_object_or_404(
        OvertimeRequest.objects.select_related('employee', 'company'), pk=pk
    )
    if not user_can_access_company(request.user, ot.company):
        raise PermissionDenied

    if request.method == 'POST':
        action = request.POST.get('action')
        ot.manager_note = request.POST.get('manager_note', ot.manager_note)

        if action == 'approve':
            raw_hours = request.POST.get('approved_hours', '').strip()
            if raw_hours:
                from decimal import Decimal, InvalidOperation
                try:
                    ot.approved_hours = Decimal(raw_hours)
                except (InvalidOperation, ValueError):
                    messages.error(request, 'Invalid approved hours value.')
                    return redirect('overtime:manage_overtime_detail', pk=ot.pk)
            else:
                ot.approved_hours = ot.requested_hours
            ot.status = 'approved'
            ot.reviewed_by = request.user
            ot.reviewed_at = timezone.now()
            ot.save()
            messages.success(request, 'Overtime request approved.')

        elif action == 'reject':
            ot.status = 'rejected'
            ot.reviewed_by = request.user
            ot.reviewed_at = timezone.now()
            ot.save()
            messages.success(request, 'Overtime request rejected.')

        return redirect('overtime:manage_overtime')

    return render(request, 'overtime/manage_overtime_detail.html', {
        'ot': ot,
    })
```

- [ ] **Step 4: Write `overtime/urls.py`**

```python
from django.urls import path

from . import views

app_name = 'overtime'

urlpatterns = [
    path('manage/', views.manage_overtime, name='manage_overtime'),
    path('manage/<int:pk>/', views.manage_overtime_detail, name='manage_overtime_detail'),
]
```

- [ ] **Step 5: Wire the app URLs in `config/urls.py`**

Add after the `holidays` include (line 29):

```python
    path('overtime/', include('overtime.urls')),
```

- [ ] **Step 6: Create `templates/overtime/manage_overtime.html`**

```html
{% extends 'base.html' %}

{% block title %}Manage Overtime{% endblock %}
{% block page_title %}Manage Overtime{% endblock %}

{% block content %}
<div class="page-header mb-3">
  <h1>Overtime Requests</h1>
  <p>HR/Admin review queue scoped to your accessible companies.</p>
</div>

<div class="card mb-3">
  <div class="card-body">
    <form method="get" class="row g-2 align-items-end">
      <div class="col-12 col-md-3">
        <label class="form-label">Status</label>
        <select name="status" class="form-select form-select-sm">
          <option value="">All statuses</option>
          {% for value, label in status_choices %}
          <option value="{{ value }}" {% if status_filter == value %}selected{% endif %}>{{ label }}</option>
          {% endfor %}
        </select>
      </div>
      <div class="col-12 col-md-3">
        <label class="form-label">Date</label>
        <input type="date" name="date" value="{{ date_filter }}" class="form-control form-control-sm">
      </div>
      <div class="col-12 col-md-6 d-flex gap-2">
        <button class="btn btn-primary btn-sm" type="submit"><i class="bi bi-funnel me-1"></i>Filter</button>
        <a href="{% url 'overtime:manage_overtime' %}" class="btn btn-outline-secondary btn-sm">Clear</a>
      </div>
    </form>
  </div>
</div>

<div class="card">
  <div class="card-header d-flex justify-content-between align-items-center">
    <span><i class="bi bi-clock-history me-1"></i>Overtime Queue</span>
    <span class="badge bg-primary rounded-pill">{{ requests|length }}</span>
  </div>
  <div class="table-responsive">
    <table class="table table-hover mb-0 align-middle" style="font-size:.875rem;">
      <thead class="table-light">
        <tr>
          <th class="ps-3">Date</th>
          <th>Employee</th>
          <th>Company</th>
          <th>Requested</th>
          <th>Source</th>
          <th>Status</th>
          <th class="text-end pe-3"></th>
        </tr>
      </thead>
      <tbody>
        {% for r in requests %}
        <tr>
          <td class="ps-3">{{ r.date|date:"M d, Y" }}</td>
          <td class="fw-semibold">{{ r.employee.full_name }}</td>
          <td>{{ r.company.name }}</td>
          <td>{{ r.requested_hours }}h</td>
          <td>{{ r.get_source_display }}</td>
          <td>{{ r.get_status_display }}</td>
          <td class="text-end pe-3">
            <a href="{% url 'overtime:manage_overtime_detail' r.pk %}" class="btn btn-sm btn-outline-primary">
              <i class="bi bi-eye me-1"></i>Open
            </a>
          </td>
        </tr>
        {% empty %}
        <tr><td colspan="7" class="text-center py-5 text-muted">No overtime requests found for your scope.</td></tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 7: Create `templates/overtime/manage_overtime_detail.html`**

```html
{% extends 'base.html' %}

{% block title %}Overtime Request{% endblock %}
{% block page_title %}Overtime Request{% endblock %}

{% block content %}
<div class="page-header mb-3">
  <h1>Overtime Request</h1>
  <p>{{ ot.employee.full_name }} — {{ ot.date|date:"M d, Y" }} ({{ ot.company.name }})</p>
</div>

<div class="card mb-3">
  <div class="card-body">
    <dl class="row mb-0">
      <dt class="col-sm-3">Requested Hours</dt><dd class="col-sm-9">{{ ot.requested_hours }}h</dd>
      <dt class="col-sm-3">Source</dt><dd class="col-sm-9">{{ ot.get_source_display }}</dd>
      <dt class="col-sm-3">Status</dt><dd class="col-sm-9">{{ ot.get_status_display }}</dd>
      <dt class="col-sm-3">Reason</dt><dd class="col-sm-9">{{ ot.reason|default:"—" }}</dd>
      {% if ot.reviewed_by %}
      <dt class="col-sm-3">Reviewed By</dt><dd class="col-sm-9">{{ ot.reviewed_by }} @ {{ ot.reviewed_at|date:"M d, Y H:i" }}</dd>
      {% endif %}
    </dl>
  </div>
</div>

<div class="card">
  <div class="card-header"><i class="bi bi-check2-square me-1"></i>Review</div>
  <div class="card-body">
    <form method="post" class="row g-3">
      {% csrf_token %}
      <div class="col-12 col-md-4">
        <label class="form-label">Approved Hours</label>
        <input type="number" step="0.25" min="0" name="approved_hours"
               value="{{ ot.approved_hours|default_if_none:ot.requested_hours }}"
               class="form-control">
        <small class="text-muted">Leave blank to approve the full requested hours.</small>
      </div>
      <div class="col-12">
        <label class="form-label">Manager Note</label>
        <textarea name="manager_note" rows="3" class="form-control">{{ ot.manager_note }}</textarea>
      </div>
      <div class="col-12 d-flex justify-content-end gap-2">
        <a href="{% url 'overtime:manage_overtime' %}" class="btn btn-outline-secondary">Back</a>
        <button type="submit" name="action" value="reject" class="btn btn-danger">
          <i class="bi bi-x-lg me-1"></i>Reject
        </button>
        <button type="submit" name="action" value="approve" class="btn btn-success">
          <i class="bi bi-check-lg me-1"></i>Approve
        </button>
      </div>
    </form>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 8: Run tests — verify they pass**

Run: `python manage.py test overtime.tests.ManageOvertimeAccessTests -v 2`
Expected: PASS (5 tests).

- [ ] **Step 9: Commit**

```bash
git add overtime/views.py overtime/urls.py config/urls.py templates/overtime/ overtime/tests.py
git commit -m "feat(overtime): company-scoped HR review pages (list/approve/reject)"
```

---

## Phase 7 — Final Verification

### Task 11: Full check + test suite + manual smoke

**Files:** none (verification only)

- [ ] **Step 1: Run the full overtime suite**

Run: `python manage.py test overtime -v 1`
Expected: OK (helper, signal, portal, HR/access — ~19 tests).

- [ ] **Step 2: Run the affected app suites**

Run: `python manage.py test attendance payroll portal overtime employees -v 1`
Expected: OK (no regressions).

- [ ] **Step 3: System check**

Run: `python manage.py check`
Expected: `System check identified no issues`.

- [ ] **Step 4: Confirm no unintended migrations are pending**

Run: `python manage.py makemigrations --check --dry-run`
Expected: `No changes detected`.

- [ ] **Step 5: Manual smoke test**

Run: `python manage.py runserver`
Then verify:
- `/portal/overtime/` shows today's schedule, policy, and (when allowed) the Request button.
- Submitting `/portal/overtime/new/` creates a pending request.
- `/overtime/manage/` (as HR/superuser) lists in-scope requests; approve sets approved_hours + review fields.
- Regenerating a payroll period reflects approved overtime only.

- [ ] **Step 6: Final commit (if any doc/cleanup changes remain)**

```bash
git add -A
git commit -m "test(overtime): verify full suite green for overtime + flexible schedules"
```

---

## Self-Review Notes (coverage map)

| Spec requirement | Task |
|------------------|------|
| Employee overtime policy (4 choices) | Task 2 |
| Flexible schedule settings (5 fields) | Task 2 |
| OvertimeRequest model (all fields + approved_hours) | Task 3 |
| Flexible attendance (no late, undertime/OT vs required) | Task 4 |
| Fixed-shift unchanged | Task 4 (regression class) |
| payable_overtime_minutes per policy | Task 5 |
| Auto-create pending for management_review | Task 6 |
| Payroll uses payable helper (holiday path too) | Task 7 |
| Employee portal: schedule + policy + request + status | Tasks 8, 9 |
| HR pages: filter, approve/reject, company-scoped | Task 10 |
| Tests for all of the above | Tasks 4–10 |
| `manage.py check` + suite + runserver | Task 11 |

**Migration checkpoints:** Tasks 2 and 3 stop for user approval before `migrate` (project rule).
