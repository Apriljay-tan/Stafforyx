# Overtime Requests + Flexible Schedules — Design

**Date:** 2026-06-03
**Branch:** `feature/overtime-flexible-schedules`
**Status:** Approved (ready for implementation plan)

## Goal

Support varied overtime and scheduling rules in Stafforyx HR:

- Fixed-shift employees (e.g. 2 PM–10 PM) keep existing late/undertime/overtime behavior.
- Flexible-schedule employees complete required daily hours within an allowed window; they
  are not late for starting later within that window, and undertime/overtime is measured
  against `required_daily_hours`.
- Overtime is governed by a per-employee policy: `not_allowed`, `automatic`,
  `request_required`, or `management_review`.
- Employees can request overtime from the portal; HR/management can review, approve, or
  reject requests (with partial-hour approval).
- Payroll pays only **payable** (policy-resolved + approved) overtime, never raw detected
  overtime.

## Non-Goals / Hard Constraints

- **Do not rewrite the attendance engine.** Flexible support is an *additive branch* in
  `compute_attendance`, guarded by `employee.flexible_schedule_enabled`.
- **Fixed-shift attendance behavior must remain byte-for-byte unchanged** when the flag is off.
- Do not break shift roster / date-based schedules (`EmployeeDailySchedule`, `ShiftTemplate`).
- Do not break payroll holiday logic.
- Do not break the existing employee portal or attendance IP/WiFi portal.
- Do not touch license validation.
- Employee portal stays employee-only; HR/admin overtime pages stay company-scoped.
- The attendance engine keeps detecting **raw** overtime only. The `overtime` app owns
  requests, approvals, manager review, and the payable-overtime computation. Payroll consumes
  the payable helper — it never reads `AttendanceRecord.overtime_minutes` directly.

## Architecture Overview

A new dedicated **`overtime` Django app** owns the request/approval domain, mirroring how
`leaves` owns `LeaveRequest`. The employee `portal` app only renders employee-facing views;
HR-facing views live in the `overtime` app (or are wired through it) and are company-scoped.

```
employees.Employee          ← new policy + flexible-schedule fields
attendance.compute_attendance ← additive flexible branch (detects raw OT only)
attendance.AttendanceRecord  ← post_save signal (in overtime app) auto-creates pending review
overtime.OvertimeRequest     ← request/approval/review records
overtime.services            ← payable_overtime_minutes(...) helper + approval index
payroll._calc_employee_payroll ← uses payable_overtime_minutes instead of raw OT
portal.views                 ← employee: today's schedule, policy, request form, status list
overtime.views               ← HR: list/filter/approve/reject, company-scoped
```

### Component responsibilities (isolation)

- **`employees.Employee`**: stores configuration only (policy + flexible settings). No behavior.
- **`attendance.compute_attendance`**: detects raw `overtime_minutes`. Policy-agnostic.
- **`overtime.services.payable_overtime_minutes`**: pure function mapping
  `(employee, date, detected_minutes, approval_index)` → payable minutes. Testable in isolation.
- **`overtime` signal**: side-effect of creating review rows; idempotent via `get_or_create`.
- **`payroll`**: orchestrates; calls the helper. No policy logic of its own.
- **`portal` / `overtime` views**: presentation + access control.

## Data Model

### Phase 1 — `Employee` new fields (migration in `employees`)

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `overtime_policy` | CharField(choices) | `not_allowed` | `not_allowed`, `automatic`, `request_required`, `management_review` |
| `flexible_schedule_enabled` | BooleanField | `False` | Master guard for flexible branch |
| `required_daily_hours` | DecimalField(4,2) | `8.00` | Used for flexible undertime/OT |
| `allowed_clock_in_from` | TimeField | null/blank | Start of allowed flexible clock-in window |
| `allowed_clock_in_until` | TimeField | null/blank | End of allowed flexible clock-in window |
| `default_break_minutes` | PositiveIntegerField | `60` | Break fallback for flexible computation |

All fields nullable/defaulted so existing employees migrate cleanly with no behavior change
(`overtime_policy='not_allowed'`, `flexible_schedule_enabled=False`).

### Phase 1 — `OvertimeRequest` model (migration in `overtime`)

| Field | Type | Notes |
|-------|------|-------|
| `company` | FK Company (CASCADE) | Company scoping |
| `employee` | FK Employee (CASCADE) | Requesting employee |
| `date` | DateField | Date OT was/will be worked |
| `requested_hours` | DecimalField(5,2) | Hours requested (or detected, for auto rows) |
| `approved_hours` | DecimalField(5,2), null/blank | Partial approval; null until reviewed |
| `reason` | TextField(blank) | Employee-supplied or "Auto-detected" |
| `status` | CharField(choices) | `pending`, `approved`, `rejected`, `auto_approved` |
| `source` | CharField(choices) | `employee`, `detected`, `hr` |
| `reviewed_by` | FK User (SET_NULL, null) | Reviewer |
| `reviewed_at` | DateTimeField(null) | Review timestamp |
| `manager_note` | TextField(blank) | Reviewer note |
| `created_at` / `updated_at` | DateTimeField | Timestamps |

- `unique_together = (employee, date)` — one OT record per employee per day; makes
  auto-create and employee submission idempotent (`get_or_create` / form guard).
- `ordering = ['-date', 'employee']`.
- Indexes on `(company, status)` and `(employee, date)`.

## Attendance Engine — Flexible Branch (Phase 2)

Modify only the **scheduled-workday** block of `attendance/services.py::compute_attendance`.
Add an early guard:

```
if employee.flexible_schedule_enabled:
    # flexible math
else:
    # EXISTING fixed-shift math (unchanged)
```

Flexible math (only when scheduled and time_in present):

- `late_min = 0` — never late for starting later within the allowed window.
- `break_min = record.break_minutes if set else employee.default_break_minutes`.
- `total_work_min = max(0, time_out − time_in − break_min)` (overnight wrap handled as today).
- `required_min = round(required_daily_hours × 60)`.
- `undertime_min = max(0, required_min − total_work_min)`.
- detected `overtime_min = max(0, total_work_min − required_min)`.
- Overtime cancels undertime (same rule as fixed path).
- `computed_status` derived the same way (overtime → undertime → late → present).

Unchanged for flexible employees: rest-day detection, no-schedule handling, absent/incomplete
states (these still come from `resolve_expected_shift`, which is **not** modified). The
employee still has a `WorkSchedule`/daily schedule for weekday/rest-day resolution and for
payroll's scheduled-day sets. `overtime_minutes` stores **detected** OT regardless of policy.

> The fixed-shift code path is untouched; flag-off employees compute exactly as before.

## Overtime Detection → Review Queue (Phase 3)

### Payable-overtime helper (`overtime/services.py`)

```
payable_overtime_minutes(employee, date, detected_min, approval_index) -> int
```

- `automatic` → `detected_min`.
- `not_allowed` → `0`, unless an approved request exists (HR manual override) → capped to
  `min(detected_min, approved_hours×60)`.
- `request_required` → `0` unless an approved request exists → `min(detected_min, approved_hours×60)`.
- `management_review` → `0` unless approved → `min(detected_min, approved_hours×60)`.

`approved_hours` falls back to `requested_hours` if null at approval time (HR may lower it).
`approval_index` is a bulk-loaded `{(employee_id, date): OvertimeRequest}` map of
approved/auto_approved requests for the payroll period (single query, matching the existing
leave/holiday batching style).

### Auto-create signal (`overtime/signals.py`)

`post_save` on `AttendanceRecord`:

- Only acts when `employee.overtime_policy == 'management_review'` and
  `record.overtime_minutes > 0`.
- `get_or_create` a `pending` `OvertimeRequest` with `source='detected'`,
  `requested_hours = overtime_minutes/60`, `reason='Auto-detected overtime'`.
- Idempotent via `unique_together`; updates `requested_hours` if the detected value changes
  while still pending (does not override an already-reviewed request).
- Other policies create nothing here. (`automatic` is paid directly; `request_required` is
  employee-initiated; `not_allowed` requires explicit HR override.)

## Payroll Integration (Phase 4)

In `payroll/services.py`:

- Build an approval index once per period (bulk query of approved/auto_approved
  `OvertimeRequest`s for the company employees in `[start_date, end_date]`).
- In `_calc_employee_payroll`, replace both `overtime_min += att.overtime_minutes` lines
  (normal pass and holiday-worked pass) with
  `overtime_min += payable_overtime_minutes(emp, date, att.overtime_minutes or 0, approval_index)`.
- No other payroll logic changes. OT multiplier, holiday pay, leave handling all unchanged.

## Employee Portal (Phase 5) — employee-only

- **Today's schedule panel**: resolved shift (via `resolve_expected_shift`) or flexible window
  + `required_daily_hours`; shows the employee's `overtime_policy`.
- **Request Overtime** button: visible only when `overtime_policy != 'not_allowed'`.
- `portal_overtime_new`: form (date, requested_hours, reason) → creates `OvertimeRequest`
  with `status='pending'`, `source='employee'`, `company=employee.company`. Blocks duplicate
  for an existing date (unique_together) with a friendly message.
- `portal_overtime_list`: employee's own requests with status. Uses `_require_portal_employee`
  ownership guard — same pattern as leaves/incidents.

## HR / Admin (Phase 6) — company-scoped

- `manage_overtime` list: filter by company, employee, status, date. Scoped with
  `filter_queryset_by_user_companies` and `can_manage_employees` / superuser check (mirrors
  `portal.manage_incidents`).
- `manage_overtime_detail`: approve/reject; set `approved_hours` and `manager_note`; stamp
  `reviewed_by` + `reviewed_at`. On approve, default `approved_hours = requested_hours` when
  left blank. Access guarded by `user_can_access_company`.
- Django admin registration for `OvertimeRequest` (company-aware list_display/filters).

## Testing (Phase 7)

Add tests before finalizing (target the seams, not the framework):

1. **Fixed-shift regression**: 2 PM–10 PM employee computes late/undertime/overtime exactly as
   before (guards "no rewrite").
2. **Flexible not-late**: flexible 8h employee starting later within the window has
   `late_minutes == 0`.
3. **Flexible undertime**: flexible employee working < required hours accrues undertime.
4. **Flexible overtime detection**: flexible employee working > required hours has detected OT.
5. **Helper — automatic**: `payable_overtime_minutes` returns detected for `automatic`.
6. **Helper — request_required**: returns 0 without approval; `min(detected, approved)` with.
7. **Helper — management_review**: 0 until approved; capped to `approved_hours`.
8. **Helper — not_allowed**: 0 unless an approved override exists.
9. **Signal**: management_review detected OT auto-creates one pending request; idempotent.
10. **Payroll**: pays approved OT only; automatic paid; request_required unpaid until approved.
11. **Portal**: employee request form creates a pending request; duplicate-date guarded.
12. **HR approval**: approve sets status/approved_hours/reviewed_by/reviewed_at.
13. **Access isolation**: employee cannot reach HR pages; HR sees only in-scope companies.

Finalize with `python manage.py check`, the test suite, and `python manage.py runserver`.

## Phasing (small, safe, incremental)

1. **Phase 1 — Models + migrations** (`employees` fields, `overtime` app + `OvertimeRequest`,
   `INSTALLED_APPS`, admin). *Ask before running migrations.*
2. **Phase 2 — Attendance flexible branch** (+ regression & flexible tests).
3. **Phase 3 — Payable helper + auto-create signal** (+ helper & signal tests).
4. **Phase 4 — Payroll integration** (+ payroll tests).
5. **Phase 5 — Employee portal** (schedule panel, request form, status list).
6. **Phase 6 — HR/admin pages** (list/filter/approve/reject, company-scoped).
7. **Phase 7 — Full verification** (`check`, tests, `runserver`).

Each phase is independently reviewable and leaves the app working.

## Open Risks / Mitigations

- **Migration safety**: all new `Employee` fields defaulted → existing rows unaffected;
  default policy `not_allowed` + flag `False` preserves current behavior. Ask before migrating.
- **Signal performance**: guarded by cheap policy/threshold check; `get_or_create` keyed on the
  unique index. Bulk attendance recompute remains O(n) with one extra guarded query per OT row.
- **Double-counting**: payroll switches fully to the helper; raw `overtime_minutes` is never
  summed directly after Phase 4.
