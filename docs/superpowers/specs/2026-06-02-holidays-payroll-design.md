# Holidays Module + Payroll Holiday Pay — Design Spec

- **Date:** 2026-06-02
- **App:** Stafforyx HR (Django 6.0.5, SQLite local)
- **Status:** Approved design (pre-implementation)

## 1. Goal

Add a Holidays module so each company can manage holidays and the rules for how
holidays are paid, and make payroll generation respect those rules — without
changing attendance/shift logic, the employee portal, or license validation.

Requirements covered: default holidays preloaded; per-company enable/disable;
per-holiday paid/unpaid; per-holiday pay multipliers; company-created holidays;
department/employee exceptions; payroll respects holidays; attendance/schedule
and portal untouched; license untouched; rules configurable (not hardcoded);
tests added.

## 2. Scope & non-goals

**In scope:** new `holidays` app (models, seeding, resolution service, UI),
payroll integration via a holiday pass, `Employee.pay_basis`, payslip holiday
line, tests.

**Non-goals / explicit limitations:**

- This is **not** a full fixed-monthly-salary payroll engine. Stafforyx pays on
  a payable-days basis (`basic_pay = daily_rate × (present_days + paid_leave_days)`,
  `daily_rate = basic_salary / 26`). That engine is preserved for everyone.
  `pay_basis='monthly'` does **not** switch an employee to a true fixed-monthly
  computation; it only changes how unpaid-by-default no-work holidays are treated
  (see §6). `daily` remains the default so existing behavior is unchanged.
- No new `Branch` model. Exceptions target Department or individual Employee.
- Holidays are exact dated entries per year. Fixed holidays can be re-seeded each
  year via the management command; movable/proclaimed holidays must be entered or
  updated yearly by an admin.
- Holiday pay applies to dates in the period that are within the employee's
  scheduled dates or have an attendance record. No-work pay applies only to
  scheduled days; worked pay applies whenever attendance exists. Rest-day-not-worked
  holidays pay nothing.

## 3. New `holidays` app

- Registered in `INSTALLED_APPS`; URLs included at `/holidays/`; sidebar nav entry.
- All views company-scoped using the existing selected-company pattern
  (`accounts.company_access`, session `selected_company_id`).
- Config UI gated behind `module_access_required('can_manage_payroll')` (reuses an
  existing permission; no `UserProfile` migration). Holidays affect pay, so this
  permission is the natural fit.

## 4. Data models (`holidays/models.py`)

### `Holiday` (always company-scoped)
| Field | Type | Notes |
|---|---|---|
| `company` | FK Company | required, `related_name='holidays'` |
| `name` | CharField(150) | |
| `date` | DateField | explicit per-year date |
| `holiday_type` | CharField choices | `regular`, `special_non_working`, `special_working`, `company`, `local` |
| `source` | CharField choices | `system_default`, `company` |
| `is_enabled` | Boolean default True | enable/disable a default |
| `is_paid` | Boolean | is a no-work day paid |
| `no_work_pay_pct` | Decimal(5,2) default 100 | % of daily rate when not worked (if paid) |
| `worked_multiplier` | Decimal(4,2) default 1.00 | **total** day multiplier when worked |
| `notes` | TextField blank | |

- `unique_together = (company, date, name)`; ordering by `date`.

### `HolidayException` (per-holiday override for a subset of staff)
| Field | Type | Notes |
|---|---|---|
| `holiday` | FK Holiday | `related_name='exceptions'` |
| `department` | FK Department null/blank | group target |
| `employee` | FK Employee null/blank | individual target (wins over department) |
| `not_observed` | Boolean default False | this group treats the day as normal |
| `is_paid_override` | Boolean null | |
| `no_work_pay_pct_override` | Decimal(5,2) null | |
| `worked_multiplier_override` | Decimal(4,2) null | |

- Validation: exactly one of `department`/`employee` set.

### `CompanyHolidayPolicy` (OneToOne Company — configurable defaults, req #11)
- `regular_no_work_pay_pct` (100.00), `regular_worked_multiplier` (2.00)
- `special_nonworking_default_paid` (False), `special_nonworking_no_work_pay_pct` (0.00), `special_nonworking_worked_multiplier` (1.30)
- `special_working_worked_multiplier` (1.00)
- `company_local_default_paid` (True), `company_local_worked_multiplier` (1.00)

Policy values seed the per-`Holiday` fields by type and act as fallback. The
per-`Holiday` row is the source of truth at resolution; exceptions override it
per group.

### `Employee.pay_basis` (new field on `employees.Employee`)
- `CharField` choices `daily` (default) | `monthly`. Default preserves current behavior.

## 5. Default seeding

- `holidays/holiday_data.py` — **pure data, no Django imports**. `DEFAULT_PH_HOLIDAYS`
  keyed by year → list of `{name, date (YYYY-MM-DD), type}`. 2026 set includes:
  - **Regular:** New Year (Jan 1), Araw ng Kagitingan (Apr 9), Maundy Thursday (Apr 2),
    Good Friday (Apr 3), Labor Day (May 1), Independence Day (Jun 12),
    National Heroes Day (Aug 31), Bonifacio Day (Nov 30), Christmas Day (Dec 25),
    Rizal Day (Dec 30).
  - **Special non-working:** Chinese New Year (Feb 17), EDSA (Feb 25), Black Saturday
    (Apr 4), Ninoy Aquino Day (Aug 21), All Saints' Day (Nov 1),
    Immaculate Conception (Dec 8), Last Day of the Year (Dec 31).
  - (Movable/proclaimed entries documented as "update yearly".)
- `holidays/seeding.py`:
  - `get_or_create_policy(company)` → `CompanyHolidayPolicy`.
  - `seed_default_holidays(company, year)` — idempotent (`get_or_create` on
    `company+date+name`), sets per-holiday pay fields from the company's policy by
    type. Returns count created.
- **Auto-seed:** `post_save` signal on `Company` (created=True) → create policy +
  seed current year. Registered in `holidays/apps.py` `ready()`.
- **Management command:** `python manage.py seed_holidays [--company ID] [--year YYYY]`
  (defaults: all companies, current year). Re-runnable/idempotent.
- **Data migration:** backfill `CompanyHolidayPolicy` + current-year holidays for
  existing companies (imports the pure-data module + a migration-safe seeding
  helper using `apps.get_model`).

## 6. Payroll integration (`payroll/services.py`)

Keep the single payable-days engine; add a **holiday pass**. No rewrite of
base/absence logic.

### Resolution (`holidays/services.py`)
- `resolve_holiday(company, employee, date, holiday_index, exception_index)` →
  `{is_paid, no_work_pay_pct, worked_multiplier, holiday}` or `None`.
  - Enabled holidays for `(company, date)`; if several share a date, pick by
    priority `regular > special_non_working > local > company > special_working`.
  - Apply exceptions (employee-specific first, else department): `not_observed`
    → `None`; otherwise apply non-null overrides.
- Batch builders `build_holiday_index(company, start, end)` and
  `build_exception_index(company)` so payroll uses bulk queries (mirrors
  `_build_scheduled_sets` / `_build_leave_maps`).

### Per-employee calculation changes
For each date in `scheduled_dates ∪ attendance_dates` that resolves to an observed
holiday:

- **Worked** (attendance present): `holiday_pay += daily_rate × worked_multiplier`.
  Exclude the date from `present_days`/`payable_days` so the base is not
  double-paid. Late/undertime/OT minutes from that day still accumulate normally.
  Net for the day = `daily_rate × multiplier`. Same for `daily` and `monthly`.
- **Not worked, scheduled day:** effective-paid =
  - `monthly` basis → **always paid** (fixed salary already covers the day; not docked);
  - `daily` basis → `holiday.is_paid` (regular paid; special-non-working unpaid
    unless the holiday/policy marks it paid).
  - if paid: `holiday_pay += daily_rate × no_work_pay_pct/100`; else nothing.
  - Exclude the date from `absent_days` (it is a holiday, not an absence).
- **Not worked, rest day (not scheduled):** no pay.

**`pay_basis` net effect (explicit):** the only behavioral difference between
`daily` and `monthly` is for **unpaid-by-default no-work holidays** (special
non-working with no paid policy): a `monthly` employee is paid that day (not
docked); a `daily` employee is not. Regular holidays pay the base in both. Worked
holidays are identical in both. This realizes "monthly salary already includes
paid holidays — avoid duplicate base pay, only add premium if worked" without a
separate fixed-monthly computation, and is covered by dedicated tests.

### Model changes (`payroll/models.py`)
- New `PayrollRecord` fields: `holiday_pay` (Decimal 12,2, added to `gross_pay`),
  `holiday_days` (PositiveInt), `holiday_worked_days` (PositiveInt).
- `recalculate()` includes `holiday_pay` in `gross_pay`.
- V2 engine returns and stores these; `generate_payroll_for_period` passes the
  holiday/exception indexes into per-employee calc.

### Payslip
- Show a holiday-pay line when `holiday_pay > 0` (classic + modern templates).

## 7. UI

- **Holiday list** (`/holidays/`): selected company's holidays, filter by type,
  inline enable/disable + paid toggle, show no-work % and worked multiplier, edit,
  **Add Holiday**. Existing Bootstrap styling.
- **Add/Edit holiday** form (custom company/local holidays; edit pay rules of any
  holiday).
- **Exceptions:** from a holiday's detail page (list + add; target department or
  employee).
- **Policy settings** page for `CompanyHolidayPolicy`.

## 8. Testing (req #12)

- **`holidays/tests.py`:** seeding (defaults created, idempotent, policy created);
  resolution (enable/disable, paid/unpaid, shared-date precedence, exceptions by
  department, by employee, `not_observed`); management command; auto-seed signal.
- **`payroll/tests.py` additions:**
  - daily regular no-work → +1 day pay (`holiday_pay == daily_rate`);
  - daily regular worked → `daily_rate × 2.00`, no double base;
  - daily special-non-working no-work (default) → unpaid; paid when policy/holiday paid;
  - special-non-working worked → `daily_rate × 1.30`;
  - **monthly** special-non-working no-work → paid (not docked), no premium;
  - **monthly** regular worked → `daily_rate × 2.00` counted once;
  - `holiday_pay` included in gross/net; `holiday_days`/`holiday_worked_days` counts.
- **Guardrails:** attendance/schedule tests unchanged; portal unaffected; license untouched.

## 9. Known impact on existing tests

Auto-seeding 2026 PH holidays means existing payroll/attendance tests that create
companies via the ORM will now have holidays in their periods (e.g.
**May 1 Labor Day** falls in existing "May 2026" periods). Where a test's
scheduled dates intersect a seeded holiday, computed pay changes legitimately.
Those test expectations will be updated to the new correct values and documented.
This is intended feature behavior, accepted by the stakeholder.

## 10. Integration points (files touched)

- New: `holidays/` (models, admin, apps, urls, views, forms, services, seeding,
  holiday_data, signals, migrations, tests), templates under `templates/holidays/`.
- Edit: `config/settings.py` (INSTALLED_APPS), `config/urls.py` (include),
  `employees/models.py` (+`pay_basis` + migration), `payroll/models.py`
  (+fields + `recalculate`), `payroll/services.py` (holiday pass),
  payslip templates, sidebar template (nav link).
- Untouched: attendance schedule logic (read-only use of `resolve_expected_shift`
  / scheduled-date sets), employee portal, license validation.
