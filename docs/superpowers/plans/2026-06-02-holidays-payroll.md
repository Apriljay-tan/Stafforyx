# Holidays Module + Payroll Holiday Pay — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-company Holidays module with default PH holidays preloaded, configurable pay rules and exceptions, and make payroll respect holidays without double-counting normal present days.

**Architecture:** New self-contained `holidays` app holds company-scoped `Holiday`, `HolidayException`, and `CompanyHolidayPolicy` models. Defaults are seeded per company (auto-seed signal on Company create + re-runnable `seed_holidays` command + data migration). A resolution service produces effective per-employee/date holiday pay parameters. The existing payable-days payroll engine gains a "holiday pass" that adds a `holiday_pay` component and excludes holiday dates from the normal present/absent classification. A new `Employee.pay_basis` (`daily` default) only changes treatment of unpaid-by-default no-work holidays for `monthly` employees.

**Tech Stack:** Django 6.0.5, SQLite (local), Bootstrap templates. Tests via `./venv/Scripts/python.exe manage.py test`.

**Reference spec:** `docs/superpowers/specs/2026-06-02-holidays-payroll-design.md`

**Branch:** `feature/holidays-payroll` (already checked out; spec already committed).

**Test command convention:** `./venv/Scripts/python.exe manage.py test <dotted.path> -v 2`

---

## Task 1: Scaffold `holidays` app + pure-data default holiday list

**Files:**
- Create: `holidays/__init__.py`, `holidays/apps.py`, `holidays/admin.py`, `holidays/migrations/__init__.py`
- Create: `holidays/constants.py`
- Create: `holidays/holiday_data.py`
- Create: `holidays/tests/__init__.py`, `holidays/tests/test_holiday_data.py`
- Modify: `config/settings.py` (add `"holidays"` to `INSTALLED_APPS`)

- [ ] **Step 1: Write the failing test**

`holidays/tests/test_holiday_data.py`:
```python
import datetime

from django.test import SimpleTestCase

from holidays.constants import (
    TYPE_REGULAR, TYPE_SPECIAL_NON_WORKING, HOLIDAY_TYPE_VALUES,
)
from holidays.holiday_data import DEFAULT_PH_HOLIDAYS, holidays_for_year


class HolidayDataTests(SimpleTestCase):
    def test_2026_set_present_and_well_formed(self):
        entries = holidays_for_year(2026)
        self.assertTrue(entries, "2026 holidays should be defined")
        names = {e["name"] for e in entries}
        self.assertIn("New Year's Day", names)
        self.assertIn("Labor Day", names)
        self.assertIn("Christmas Day", names)
        for e in entries:
            self.assertEqual(e["date"].year, 2026)
            self.assertIn(e["type"], HOLIDAY_TYPE_VALUES)

    def test_labor_day_is_regular_may_1(self):
        entries = {e["name"]: e for e in holidays_for_year(2026)}
        labor = entries["Labor Day"]
        self.assertEqual(labor["date"], datetime.date(2026, 5, 1))
        self.assertEqual(labor["type"], TYPE_REGULAR)

    def test_unknown_year_returns_empty(self):
        self.assertEqual(holidays_for_year(1900), [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe manage.py test holidays.tests.test_holiday_data -v 2`
Expected: FAIL — `ModuleNotFoundError: No module named 'holidays'`.

- [ ] **Step 3: Create the app scaffold**

`holidays/__init__.py`: empty.

`holidays/migrations/__init__.py`: empty.

`holidays/apps.py`:
```python
from django.apps import AppConfig


class HolidaysConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "holidays"
    verbose_name = "Holidays"

    def ready(self):
        # Import signal handlers (registered in Task 4).
        from . import signals  # noqa: F401
```

> NOTE: `signals.py` is created in Task 4. Until then, temporarily comment the
> import body of `ready()` OR create an empty `holidays/signals.py` now to keep
> the app importable. Create empty `holidays/signals.py` now:

`holidays/signals.py` (placeholder, filled in Task 4):
```python
# Signal handlers registered in apps.ready(). Populated in Task 4.
```

`holidays/admin.py`:
```python
from django.contrib import admin

# Model admins registered in Task 2.
```

`holidays/constants.py`:
```python
TYPE_REGULAR = "regular"
TYPE_SPECIAL_NON_WORKING = "special_non_working"
TYPE_SPECIAL_WORKING = "special_working"
TYPE_COMPANY = "company"
TYPE_LOCAL = "local"

HOLIDAY_TYPE_CHOICES = [
    (TYPE_REGULAR, "Regular Holiday"),
    (TYPE_SPECIAL_NON_WORKING, "Special (Non-Working)"),
    (TYPE_SPECIAL_WORKING, "Special (Working)"),
    (TYPE_COMPANY, "Company Holiday"),
    (TYPE_LOCAL, "Local Holiday"),
]
HOLIDAY_TYPE_VALUES = {c[0] for c in HOLIDAY_TYPE_CHOICES}

SOURCE_SYSTEM_DEFAULT = "system_default"
SOURCE_COMPANY = "company"
SOURCE_CHOICES = [
    (SOURCE_SYSTEM_DEFAULT, "System Default"),
    (SOURCE_COMPANY, "Company"),
]

# Resolution priority when multiple holidays share one date (lower = higher priority).
TYPE_PRIORITY = {
    TYPE_REGULAR: 0,
    TYPE_SPECIAL_NON_WORKING: 1,
    TYPE_LOCAL: 2,
    TYPE_COMPANY: 3,
    TYPE_SPECIAL_WORKING: 4,
}
```

`holidays/holiday_data.py`:
```python
"""Pure-data default Philippine holiday catalog. No Django imports.

Fixed-date holidays can be re-seeded each year via `seed_holidays`.
Movable/proclaimed holidays (Maundy Thursday, Good Friday, Black Saturday,
Chinese New Year, Eid, etc.) are explicit per year and MUST be updated yearly.
"""
import datetime

from .constants import (
    TYPE_REGULAR, TYPE_SPECIAL_NON_WORKING,
)

# year -> list of (name, (month, day), type)
_RAW = {
    2026: [
        ("New Year's Day", (1, 1), TYPE_REGULAR),
        ("Araw ng Kagitingan", (4, 9), TYPE_REGULAR),
        ("Maundy Thursday", (4, 2), TYPE_REGULAR),
        ("Good Friday", (4, 3), TYPE_REGULAR),
        ("Labor Day", (5, 1), TYPE_REGULAR),
        ("Independence Day", (6, 12), TYPE_REGULAR),
        ("National Heroes Day", (8, 31), TYPE_REGULAR),
        ("Bonifacio Day", (11, 30), TYPE_REGULAR),
        ("Christmas Day", (12, 25), TYPE_REGULAR),
        ("Rizal Day", (12, 30), TYPE_REGULAR),
        ("Chinese New Year", (2, 17), TYPE_SPECIAL_NON_WORKING),
        ("EDSA People Power Anniversary", (2, 25), TYPE_SPECIAL_NON_WORKING),
        ("Black Saturday", (4, 4), TYPE_SPECIAL_NON_WORKING),
        ("Ninoy Aquino Day", (8, 21), TYPE_SPECIAL_NON_WORKING),
        ("All Saints' Day", (11, 1), TYPE_SPECIAL_NON_WORKING),
        ("Feast of the Immaculate Conception", (12, 8), TYPE_SPECIAL_NON_WORKING),
        ("Last Day of the Year", (12, 31), TYPE_SPECIAL_NON_WORKING),
    ],
}

DEFAULT_PH_HOLIDAYS = {
    year: [
        {"name": name, "date": datetime.date(year, m, d), "type": htype}
        for (name, (m, d), htype) in entries
    ]
    for year, entries in _RAW.items()
}


def holidays_for_year(year):
    """Return a list of {name, date, type} dicts for the given year (or [])."""
    return list(DEFAULT_PH_HOLIDAYS.get(year, []))
```

- [ ] **Step 4: Register the app**

Modify `config/settings.py` `INSTALLED_APPS` — add `"holidays",` after `"portal",`:
```python
    "portal",
    "holidays",
]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `./venv/Scripts/python.exe manage.py test holidays.tests.test_holiday_data -v 2`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add holidays config/settings.py
git commit -m "Scaffold holidays app with default PH holiday data"
```

---

## Task 2: Models — Holiday, HolidayException, CompanyHolidayPolicy, Employee.pay_basis

**Files:**
- Create: `holidays/models.py`
- Modify: `holidays/admin.py`
- Modify: `employees/models.py` (add `pay_basis`)
- Create (generated): `holidays/migrations/0001_initial.py`, `employees/migrations/000X_pay_basis.py`
- Create: `holidays/tests/test_models.py`

- [ ] **Step 1: Write the failing test**

`holidays/tests/test_models.py`:
```python
import datetime

from django.core.exceptions import ValidationError
from django.db.utils import IntegrityError
from django.test import TestCase

from companies.models import Company
from employees.models import Department, Employee
from holidays.constants import TYPE_REGULAR, SOURCE_COMPANY
from holidays.models import CompanyHolidayPolicy, Holiday, HolidayException


def make_company(name="Acme"):
    return Company.objects.create(name=name, email=f"{name.lower()}@t.com")


class HolidayModelTests(TestCase):
    def setUp(self):
        self.company = make_company()

    def test_create_holiday_defaults(self):
        h = Holiday.objects.create(
            company=self.company, name="Christmas Day",
            date=datetime.date(2026, 12, 25), holiday_type=TYPE_REGULAR,
            source=SOURCE_COMPANY, is_paid=True,
        )
        self.assertTrue(h.is_enabled)
        self.assertEqual(str(h.no_work_pay_pct), "100.00")
        self.assertEqual(str(h.worked_multiplier), "1.00")

    def test_unique_company_date_name(self):
        kw = dict(company=self.company, name="X",
                  date=datetime.date(2026, 1, 1), holiday_type=TYPE_REGULAR)
        Holiday.objects.create(**kw)
        with self.assertRaises(IntegrityError):
            Holiday.objects.create(**kw)

    def test_policy_defaults(self):
        p = CompanyHolidayPolicy.objects.create(company=self.company)
        self.assertEqual(str(p.regular_worked_multiplier), "2.00")
        self.assertEqual(str(p.special_nonworking_worked_multiplier), "1.30")
        self.assertFalse(p.special_nonworking_default_paid)

    def test_exception_requires_exactly_one_target(self):
        h = Holiday.objects.create(
            company=self.company, name="X", date=datetime.date(2026, 1, 1),
            holiday_type=TYPE_REGULAR,
        )
        exc = HolidayException(holiday=h)  # neither department nor employee
        with self.assertRaises(ValidationError):
            exc.full_clean()


class EmployeePayBasisTests(TestCase):
    def test_default_pay_basis_is_daily(self):
        company = make_company("E")
        dept = Department.objects.create(company=company, name="Ops")
        emp = Employee.objects.create(
            company=company, employee_id="E1", first_name="A", last_name="B",
            email="a@b.com", date_hired=datetime.date(2024, 1, 1), department=dept,
        )
        self.assertEqual(emp.pay_basis, "daily")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe manage.py test holidays.tests.test_models -v 2`
Expected: FAIL — `cannot import name 'Holiday'`.

- [ ] **Step 3: Write the models**

`holidays/models.py`:
```python
from django.core.exceptions import ValidationError
from django.db import models

from companies.models import Company
from employees.models import Department, Employee

from .constants import HOLIDAY_TYPE_CHOICES, SOURCE_CHOICES, SOURCE_COMPANY


class Holiday(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="holidays")
    name = models.CharField(max_length=150)
    date = models.DateField()
    holiday_type = models.CharField(max_length=30, choices=HOLIDAY_TYPE_CHOICES)
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default=SOURCE_COMPANY)
    is_enabled = models.BooleanField(default=True)
    is_paid = models.BooleanField(default=True)
    no_work_pay_pct = models.DecimalField(max_digits=5, decimal_places=2, default=100)
    worked_multiplier = models.DecimalField(max_digits=4, decimal_places=2, default=1)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["date", "name"]
        unique_together = ("company", "date", "name")

    def __str__(self):
        return f"{self.name} ({self.date}) — {self.company.name}"


class HolidayException(models.Model):
    holiday = models.ForeignKey(Holiday, on_delete=models.CASCADE, related_name="exceptions")
    department = models.ForeignKey(
        Department, on_delete=models.CASCADE, null=True, blank=True,
        related_name="holiday_exceptions",
    )
    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, null=True, blank=True,
        related_name="holiday_exceptions",
    )
    not_observed = models.BooleanField(default=False)
    is_paid_override = models.BooleanField(null=True, blank=True)
    no_work_pay_pct_override = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True)
    worked_multiplier_override = models.DecimalField(
        max_digits=4, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["holiday", "department", "employee"]

    def clean(self):
        targets = [self.department_id, self.employee_id]
        set_count = sum(1 for t in targets if t)
        if set_count != 1:
            raise ValidationError(
                "Set exactly one target: either a department or an employee."
            )

    def __str__(self):
        target = self.employee or self.department
        return f"Exception: {self.holiday.name} → {target}"


class CompanyHolidayPolicy(models.Model):
    company = models.OneToOneField(
        Company, on_delete=models.CASCADE, related_name="holiday_policy")
    regular_no_work_pay_pct = models.DecimalField(max_digits=5, decimal_places=2, default=100)
    regular_worked_multiplier = models.DecimalField(max_digits=4, decimal_places=2, default=2)
    special_nonworking_default_paid = models.BooleanField(default=False)
    special_nonworking_no_work_pay_pct = models.DecimalField(
        max_digits=5, decimal_places=2, default=0)
    special_nonworking_worked_multiplier = models.DecimalField(
        max_digits=4, decimal_places=2, default=Decimal("1.30"))
    special_working_worked_multiplier = models.DecimalField(
        max_digits=4, decimal_places=2, default=1)
    company_local_default_paid = models.BooleanField(default=True)
    company_local_worked_multiplier = models.DecimalField(
        max_digits=4, decimal_places=2, default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Company holiday policies"

    def __str__(self):
        return f"Holiday Policy — {self.company.name}"
```

Add the missing import at the top of `holidays/models.py`:
```python
from decimal import Decimal
```

- [ ] **Step 4: Add `pay_basis` to Employee**

Modify `employees/models.py` — inside `class Employee`, add the choice list near `STATUS_CHOICES` and the field near `basic_salary`:
```python
    PAY_BASIS_CHOICES = [
        ('daily', 'Daily / Payable-days'),
        ('monthly', 'Monthly (fixed salary includes holidays)'),
    ]
```
And below `basic_salary = ...`:
```python
    pay_basis = models.CharField(
        max_length=10, choices=PAY_BASIS_CHOICES, default='daily',
        help_text='Daily: paid per payable day. Monthly: fixed salary already '
                  'includes paid holidays (no-work holidays are not docked).',
    )
```

- [ ] **Step 5: Register admin**

`holidays/admin.py`:
```python
from django.contrib import admin

from .models import CompanyHolidayPolicy, Holiday, HolidayException


@admin.register(Holiday)
class HolidayAdmin(admin.ModelAdmin):
    list_display = ("name", "date", "holiday_type", "company", "is_enabled", "is_paid")
    list_filter = ("holiday_type", "is_enabled", "is_paid", "company")
    search_fields = ("name",)


@admin.register(HolidayException)
class HolidayExceptionAdmin(admin.ModelAdmin):
    list_display = ("holiday", "department", "employee", "not_observed")


@admin.register(CompanyHolidayPolicy)
class CompanyHolidayPolicyAdmin(admin.ModelAdmin):
    list_display = ("company",)
```

- [ ] **Step 6: Make and run migrations**

Run:
```bash
./venv/Scripts/python.exe manage.py makemigrations holidays employees
./venv/Scripts/python.exe manage.py migrate
```
Expected: `holidays/migrations/0001_initial.py` and an `employees` migration created; migrate OK.

- [ ] **Step 7: Run tests**

Run: `./venv/Scripts/python.exe manage.py test holidays.tests.test_models -v 2`
Expected: PASS (5 tests).

- [ ] **Step 8: Commit**

```bash
git add holidays employees
git commit -m "Add Holiday, HolidayException, CompanyHolidayPolicy models and Employee.pay_basis"
```

---

## Task 3: Seeding helpers (policy + default holidays, idempotent)

**Files:**
- Create: `holidays/seeding.py`
- Create: `holidays/tests/test_seeding.py`

- [ ] **Step 1: Write the failing test**

`holidays/tests/test_seeding.py`:
```python
from django.test import TestCase

from companies.models import Company
from holidays.constants import (
    SOURCE_SYSTEM_DEFAULT, TYPE_REGULAR, TYPE_SPECIAL_NON_WORKING,
)
from holidays.holiday_data import holidays_for_year
from holidays.models import CompanyHolidayPolicy, Holiday
from holidays.seeding import get_or_create_policy, seed_default_holidays


class SeedingTests(TestCase):
    def setUp(self):
        # Company creation auto-seeds (Task 4). Use update_or_create-free company
        # and clear to test seeding in isolation.
        self.company = Company.objects.create(name="Seed Co", email="s@t.com")
        Holiday.objects.filter(company=self.company).delete()

    def test_seed_creates_expected_count_and_fields(self):
        created = seed_default_holidays(self.company, 2026)
        expected = len(holidays_for_year(2026))
        self.assertEqual(created, expected)
        self.assertEqual(Holiday.objects.filter(company=self.company).count(), expected)

        labor = Holiday.objects.get(company=self.company, name="Labor Day")
        self.assertEqual(labor.holiday_type, TYPE_REGULAR)
        self.assertEqual(labor.source, SOURCE_SYSTEM_DEFAULT)
        self.assertTrue(labor.is_paid)
        self.assertEqual(str(labor.worked_multiplier), "2.00")   # from policy
        self.assertEqual(str(labor.no_work_pay_pct), "100.00")

        edsa = Holiday.objects.get(company=self.company, name="EDSA People Power Anniversary")
        self.assertEqual(edsa.holiday_type, TYPE_SPECIAL_NON_WORKING)
        self.assertFalse(edsa.is_paid)                            # default not paid
        self.assertEqual(str(edsa.worked_multiplier), "1.30")
        self.assertEqual(str(edsa.no_work_pay_pct), "0.00")

    def test_seed_is_idempotent(self):
        seed_default_holidays(self.company, 2026)
        again = seed_default_holidays(self.company, 2026)
        self.assertEqual(again, 0)
        self.assertEqual(
            Holiday.objects.filter(company=self.company).count(),
            len(holidays_for_year(2026)),
        )

    def test_get_or_create_policy(self):
        CompanyHolidayPolicy.objects.filter(company=self.company).delete()
        p1 = get_or_create_policy(self.company)
        p2 = get_or_create_policy(self.company)
        self.assertEqual(p1.pk, p2.pk)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe manage.py test holidays.tests.test_seeding -v 2`
Expected: FAIL — `No module named 'holidays.seeding'`.

- [ ] **Step 3: Write the seeding module**

`holidays/seeding.py`:
```python
"""Seed default holidays and policy for a company. Idempotent."""
from .constants import (
    SOURCE_SYSTEM_DEFAULT, TYPE_REGULAR, TYPE_SPECIAL_NON_WORKING,
    TYPE_SPECIAL_WORKING, TYPE_COMPANY, TYPE_LOCAL,
)
from .holiday_data import holidays_for_year
from .models import CompanyHolidayPolicy, Holiday


def get_or_create_policy(company):
    policy, _ = CompanyHolidayPolicy.objects.get_or_create(company=company)
    return policy


def _pay_fields_for_type(policy, holiday_type):
    """Return (is_paid, no_work_pay_pct, worked_multiplier) for a type from policy."""
    if holiday_type == TYPE_REGULAR:
        return True, policy.regular_no_work_pay_pct, policy.regular_worked_multiplier
    if holiday_type == TYPE_SPECIAL_NON_WORKING:
        return (
            policy.special_nonworking_default_paid,
            policy.special_nonworking_no_work_pay_pct,
            policy.special_nonworking_worked_multiplier,
        )
    if holiday_type == TYPE_SPECIAL_WORKING:
        return True, 100, policy.special_working_worked_multiplier
    # company / local
    return (
        policy.company_local_default_paid,
        100 if policy.company_local_default_paid else 0,
        policy.company_local_worked_multiplier,
    )


def seed_default_holidays(company, year):
    """Create system-default Holiday rows for `company` and `year`. Returns count created."""
    policy = get_or_create_policy(company)
    created = 0
    for entry in holidays_for_year(year):
        is_paid, no_work_pct, worked_mult = _pay_fields_for_type(policy, entry["type"])
        _, was_created = Holiday.objects.get_or_create(
            company=company, date=entry["date"], name=entry["name"],
            defaults=dict(
                holiday_type=entry["type"],
                source=SOURCE_SYSTEM_DEFAULT,
                is_enabled=True,
                is_paid=is_paid,
                no_work_pay_pct=no_work_pct,
                worked_multiplier=worked_mult,
            ),
        )
        if was_created:
            created += 1
    return created
```

- [ ] **Step 4: Run tests**

Run: `./venv/Scripts/python.exe manage.py test holidays.tests.test_seeding -v 2`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add holidays/seeding.py holidays/tests/test_seeding.py
git commit -m "Add idempotent holiday + policy seeding helpers"
```

---

## Task 4: Auto-seed signal on Company create

**Files:**
- Modify: `holidays/signals.py`
- Create: `holidays/tests/test_signals.py`

- [ ] **Step 1: Write the failing test**

`holidays/tests/test_signals.py`:
```python
import datetime

from django.test import TestCase

from companies.models import Company
from holidays.holiday_data import holidays_for_year
from holidays.models import CompanyHolidayPolicy, Holiday


class AutoSeedSignalTests(TestCase):
    def test_creating_company_seeds_current_year_and_policy(self):
        # The seeding signal uses datetime.date.today().year; today is 2026.
        company = Company.objects.create(name="Signal Co", email="sig@t.com")
        year = datetime.date.today().year
        expected = len(holidays_for_year(year))
        self.assertEqual(Holiday.objects.filter(company=company).count(), expected)
        self.assertTrue(CompanyHolidayPolicy.objects.filter(company=company).exists())

    def test_signal_is_safe_on_update(self):
        company = Company.objects.create(name="Up Co", email="up@t.com")
        before = Holiday.objects.filter(company=company).count()
        company.name = "Up Co 2"
        company.save()
        self.assertEqual(Holiday.objects.filter(company=company).count(), before)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe manage.py test holidays.tests.test_signals -v 2`
Expected: FAIL — counts are 0 (no signal yet).

- [ ] **Step 3: Implement the signal**

`holidays/signals.py` (replace placeholder):
```python
import datetime

from django.db.models.signals import post_save
from django.dispatch import receiver

from companies.models import Company


@receiver(post_save, sender=Company, dispatch_uid="holidays_seed_on_company_create")
def seed_holidays_for_new_company(sender, instance, created, **kwargs):
    if not created:
        return
    # Local import avoids app-loading issues at import time.
    from .seeding import seed_default_holidays
    seed_default_holidays(instance, datetime.date.today().year)
```

Confirm `holidays/apps.py` `ready()` imports `signals` (done in Task 1).

- [ ] **Step 4: Run tests**

Run: `./venv/Scripts/python.exe manage.py test holidays.tests.test_signals -v 2`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add holidays/signals.py holidays/tests/test_signals.py
git commit -m "Auto-seed default holidays when a company is created"
```

---

## Task 5: `seed_holidays` management command

**Files:**
- Create: `holidays/management/__init__.py`, `holidays/management/commands/__init__.py`
- Create: `holidays/management/commands/seed_holidays.py`
- Create: `holidays/tests/test_command.py`

- [ ] **Step 1: Write the failing test**

`holidays/tests/test_command.py`:
```python
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from companies.models import Company
from holidays.holiday_data import holidays_for_year
from holidays.models import Holiday


class SeedHolidaysCommandTests(TestCase):
    def setUp(self):
        self.c1 = Company.objects.create(name="C1", email="c1@t.com")
        self.c2 = Company.objects.create(name="C2", email="c2@t.com")
        Holiday.objects.all().delete()  # clear auto-seeded rows

    def test_seeds_all_companies_for_year(self):
        out = StringIO()
        call_command("seed_holidays", "--year", "2026", stdout=out)
        expected = len(holidays_for_year(2026))
        self.assertEqual(Holiday.objects.filter(company=self.c1).count(), expected)
        self.assertEqual(Holiday.objects.filter(company=self.c2).count(), expected)

    def test_seeds_single_company(self):
        call_command("seed_holidays", "--company", str(self.c1.pk), "--year", "2026")
        self.assertEqual(
            Holiday.objects.filter(company=self.c1).count(), len(holidays_for_year(2026)))
        self.assertEqual(Holiday.objects.filter(company=self.c2).count(), 0)

    def test_idempotent(self):
        call_command("seed_holidays", "--year", "2026")
        call_command("seed_holidays", "--year", "2026")
        self.assertEqual(
            Holiday.objects.filter(company=self.c1).count(), len(holidays_for_year(2026)))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe manage.py test holidays.tests.test_command -v 2`
Expected: FAIL — `Unknown command: 'seed_holidays'`.

- [ ] **Step 3: Implement the command**

`holidays/management/__init__.py`: empty.
`holidays/management/commands/__init__.py`: empty.

`holidays/management/commands/seed_holidays.py`:
```python
import datetime

from django.core.management.base import BaseCommand

from companies.models import Company
from holidays.seeding import seed_default_holidays


class Command(BaseCommand):
    help = "Seed default Philippine holidays for companies."

    def add_arguments(self, parser):
        parser.add_argument("--company", type=int, default=None,
                            help="Company ID. Omit to seed all companies.")
        parser.add_argument("--year", type=int, default=datetime.date.today().year,
                            help="Year to seed (default: current year).")

    def handle(self, *args, **options):
        year = options["year"]
        if options["company"]:
            companies = Company.objects.filter(pk=options["company"])
        else:
            companies = Company.objects.all()

        total = 0
        for company in companies:
            created = seed_default_holidays(company, year)
            total += created
            self.stdout.write(f"{company.name}: +{created} holiday(s) for {year}")
        self.stdout.write(self.style.SUCCESS(f"Done. {total} holiday(s) created."))
```

- [ ] **Step 4: Run tests**

Run: `./venv/Scripts/python.exe manage.py test holidays.tests.test_command -v 2`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add holidays/management holidays/tests/test_command.py
git commit -m "Add re-runnable seed_holidays management command"
```

---

## Task 6: Data migration to backfill existing companies

**Files:**
- Create: `holidays/migrations/0002_seed_existing_companies.py`

- [ ] **Step 1: Write the data migration**

`holidays/migrations/0002_seed_existing_companies.py`:
```python
import datetime

from django.db import migrations

from holidays.constants import (
    SOURCE_SYSTEM_DEFAULT, TYPE_REGULAR, TYPE_SPECIAL_NON_WORKING,
    TYPE_SPECIAL_WORKING,
)
from holidays.holiday_data import holidays_for_year


def _pay_fields(policy, htype):
    if htype == TYPE_REGULAR:
        return True, policy.regular_no_work_pay_pct, policy.regular_worked_multiplier
    if htype == TYPE_SPECIAL_NON_WORKING:
        return (policy.special_nonworking_default_paid,
                policy.special_nonworking_no_work_pay_pct,
                policy.special_nonworking_worked_multiplier)
    if htype == TYPE_SPECIAL_WORKING:
        return True, 100, policy.special_working_worked_multiplier
    return (policy.company_local_default_paid,
            100 if policy.company_local_default_paid else 0,
            policy.company_local_worked_multiplier)


def backfill(apps, schema_editor):
    Company = apps.get_model("companies", "Company")
    Holiday = apps.get_model("holidays", "Holiday")
    Policy = apps.get_model("holidays", "CompanyHolidayPolicy")
    year = datetime.date.today().year
    for company in Company.objects.all():
        policy, _ = Policy.objects.get_or_create(company=company)
        for entry in holidays_for_year(year):
            is_paid, no_work_pct, worked_mult = _pay_fields(policy, entry["type"])
            Holiday.objects.get_or_create(
                company=company, date=entry["date"], name=entry["name"],
                defaults=dict(
                    holiday_type=entry["type"], source=SOURCE_SYSTEM_DEFAULT,
                    is_enabled=True, is_paid=is_paid,
                    no_work_pay_pct=no_work_pct, worked_multiplier=worked_mult,
                ),
            )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [("holidays", "0001_initial")]
    operations = [migrations.RunPython(backfill, noop)]
```

> NOTE: importing `holidays.constants` / `holidays.holiday_data` in a migration is
> safe because they are pure-Python with no model imports. We intentionally use
> `apps.get_model` for ORM access.

- [ ] **Step 2: Run migrate and check**

Run:
```bash
./venv/Scripts/python.exe manage.py migrate
./venv/Scripts/python.exe manage.py check
```
Expected: migration `0002_seed_existing_companies` applies; check reports no issues.

- [ ] **Step 3: Commit**

```bash
git add holidays/migrations/0002_seed_existing_companies.py
git commit -m "Backfill default holidays for existing companies via data migration"
```

---

## Task 7: Holiday resolution service (priority + exceptions + batch indexes)

**Files:**
- Create: `holidays/services.py`
- Create: `holidays/tests/test_services.py`

- [ ] **Step 1: Write the failing test**

`holidays/tests/test_services.py`:
```python
import datetime

from django.test import TestCase

from companies.models import Company
from employees.models import Department, Employee
from holidays.constants import (
    TYPE_REGULAR, TYPE_SPECIAL_NON_WORKING, TYPE_LOCAL, SOURCE_COMPANY,
)
from holidays.models import Holiday, HolidayException
from holidays.services import (
    build_exception_index, build_holiday_index, resolve_holiday,
)

D = datetime.date


def emp(company, dept=None, eid="E1"):
    return Employee.objects.create(
        company=company, employee_id=eid, first_name="A", last_name="B",
        email=f"{eid}@b.com", date_hired=D(2024, 1, 1), department=dept,
    )


class ResolveHolidayTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="R", email="r@t.com")
        Holiday.objects.filter(company=self.company).delete()
        self.dept = Department.objects.create(company=self.company, name="Ops")
        self.e = emp(self.company, self.dept)

    def _resolve(self, date):
        hidx = build_holiday_index(self.company, date, date)
        eidx = build_exception_index(self.company)
        return resolve_holiday(self.company, self.e, date, hidx, eidx)

    def test_no_holiday_returns_none(self):
        self.assertIsNone(self._resolve(D(2026, 3, 3)))

    def test_disabled_holiday_returns_none(self):
        Holiday.objects.create(company=self.company, name="X", date=D(2026, 3, 3),
                               holiday_type=TYPE_REGULAR, is_enabled=False)
        self.assertIsNone(self._resolve(D(2026, 3, 3)))

    def test_regular_holiday_resolves_paid(self):
        Holiday.objects.create(company=self.company, name="Reg", date=D(2026, 5, 1),
                               holiday_type=TYPE_REGULAR, is_paid=True,
                               no_work_pay_pct=100, worked_multiplier=2)
        r = self._resolve(D(2026, 5, 1))
        self.assertTrue(r["is_paid"])
        self.assertEqual(str(r["worked_multiplier"]), "2.00")

    def test_priority_regular_over_local_on_same_date(self):
        Holiday.objects.create(company=self.company, name="Local", date=D(2026, 5, 1),
                               holiday_type=TYPE_LOCAL, worked_multiplier=1)
        Holiday.objects.create(company=self.company, name="Reg", date=D(2026, 5, 1),
                               holiday_type=TYPE_REGULAR, worked_multiplier=2)
        r = self._resolve(D(2026, 5, 1))
        self.assertEqual(r["holiday"].holiday_type, TYPE_REGULAR)

    def test_employee_exception_not_observed(self):
        h = Holiday.objects.create(company=self.company, name="Reg", date=D(2026, 5, 1),
                                   holiday_type=TYPE_REGULAR)
        HolidayException.objects.create(holiday=h, employee=self.e, not_observed=True)
        self.assertIsNone(self._resolve(D(2026, 5, 1)))

    def test_department_exception_overrides_pay(self):
        h = Holiday.objects.create(company=self.company, name="SNW", date=D(2026, 2, 25),
                                   holiday_type=TYPE_SPECIAL_NON_WORKING, is_paid=False,
                                   worked_multiplier=Decimal("1.30"))
        HolidayException.objects.create(holiday=h, department=self.dept,
                                        is_paid_override=True, no_work_pay_pct_override=100)
        r = self._resolve(D(2026, 2, 25))
        self.assertTrue(r["is_paid"])
        self.assertEqual(str(r["no_work_pay_pct"]), "100.00")

    def test_employee_exception_beats_department(self):
        h = Holiday.objects.create(company=self.company, name="SNW", date=D(2026, 2, 25),
                                   holiday_type=TYPE_SPECIAL_NON_WORKING, is_paid=False)
        HolidayException.objects.create(holiday=h, department=self.dept, is_paid_override=True)
        HolidayException.objects.create(holiday=h, employee=self.e, not_observed=True)
        self.assertIsNone(self._resolve(D(2026, 2, 25)))
```

Add at the top of the test file:
```python
from decimal import Decimal
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe manage.py test holidays.tests.test_services -v 2`
Expected: FAIL — `No module named 'holidays.services'`.

- [ ] **Step 3: Implement the service**

`holidays/services.py`:
```python
"""Resolve the effective holiday (and pay parameters) for an employee on a date.

Batch builders let payroll resolve many employees/dates with few queries.
"""
from collections import defaultdict

from .constants import TYPE_PRIORITY
from .models import Holiday, HolidayException


def build_holiday_index(company, start_date, end_date):
    """{date: [Holiday, ...]} for enabled holidays in [start, end], sorted by priority."""
    index = defaultdict(list)
    qs = Holiday.objects.filter(
        company=company, is_enabled=True,
        date__gte=start_date, date__lte=end_date,
    )
    for h in qs:
        index[h.date].append(h)
    for date in index:
        index[date].sort(key=lambda h: TYPE_PRIORITY.get(h.holiday_type, 99))
    return index


def build_exception_index(company):
    """{holiday_id: {'dept': {dept_id: exc}, 'emp': {emp_id: exc}}}."""
    index = defaultdict(lambda: {"dept": {}, "emp": {}})
    qs = HolidayException.objects.filter(holiday__company=company)
    for exc in qs.select_related("holiday"):
        if exc.employee_id:
            index[exc.holiday_id]["emp"][exc.employee_id] = exc
        elif exc.department_id:
            index[exc.holiday_id]["dept"][exc.department_id] = exc
    return index


def _effective_params(holiday, exc):
    is_paid = holiday.is_paid
    no_work_pct = holiday.no_work_pay_pct
    worked_mult = holiday.worked_multiplier
    if exc is not None:
        if exc.is_paid_override is not None:
            is_paid = exc.is_paid_override
        if exc.no_work_pay_pct_override is not None:
            no_work_pct = exc.no_work_pay_pct_override
        if exc.worked_multiplier_override is not None:
            worked_mult = exc.worked_multiplier_override
    return {
        "holiday": holiday,
        "is_paid": is_paid,
        "no_work_pay_pct": no_work_pct,
        "worked_multiplier": worked_mult,
    }


def resolve_holiday(company, employee, date, holiday_index, exception_index):
    """Return effective holiday pay params for employee+date, or None.

    None means: no holiday, all holidays disabled, or an exception marks the
    highest-priority holiday `not_observed` for this employee/department.
    """
    candidates = holiday_index.get(date)
    if not candidates:
        return None

    holiday = candidates[0]  # highest priority
    exc_for_holiday = exception_index.get(holiday.id)
    exc = None
    if exc_for_holiday:
        exc = exc_for_holiday["emp"].get(employee.id)
        if exc is None and employee.department_id:
            exc = exc_for_holiday["dept"].get(employee.department_id)

    if exc is not None and exc.not_observed:
        return None

    return _effective_params(holiday, exc)
```

- [ ] **Step 4: Run tests**

Run: `./venv/Scripts/python.exe manage.py test holidays.tests.test_services -v 2`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add holidays/services.py holidays/tests/test_services.py
git commit -m "Add holiday resolution service with priority and exceptions"
```

---

## Task 8: PayrollRecord holiday fields + recalculate

**Files:**
- Modify: `payroll/models.py`
- Create (generated): `payroll/migrations/000X_holiday_pay.py`
- Create: `payroll/tests_holiday_record.py`

- [ ] **Step 1: Write the failing test**

`payroll/tests_holiday_record.py`:
```python
import datetime
from decimal import Decimal

from django.test import TestCase

from companies.models import Company
from employees.models import Employee
from payroll.models import PayrollPeriod, PayrollRecord


class HolidayPayRecalculateTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="P", email="p@t.com")
        self.period = PayrollPeriod.objects.create(
            company=self.company, name="May 2026",
            start_date=datetime.date(2026, 5, 1), end_date=datetime.date(2026, 5, 15),
        )
        self.emp = Employee.objects.create(
            company=self.company, employee_id="E1", first_name="A", last_name="B",
            email="a@b.com", date_hired=datetime.date(2024, 1, 1), basic_salary=26000,
        )

    def test_holiday_pay_included_in_gross_and_net(self):
        rec = PayrollRecord.objects.create(
            company=self.company, payroll_period=self.period, employee=self.emp,
            basic_pay=Decimal("10000.00"), holiday_pay=Decimal("2000.00"),
        )
        rec.recalculate()
        rec.refresh_from_db()
        self.assertEqual(rec.gross_pay, Decimal("12000.00"))
        self.assertEqual(rec.net_pay, Decimal("12000.00"))

    def test_holiday_fields_default_zero(self):
        rec = PayrollRecord.objects.create(
            company=self.company, payroll_period=self.period, employee=self.emp)
        self.assertEqual(rec.holiday_pay, Decimal("0"))
        self.assertEqual(rec.holiday_days, 0)
        self.assertEqual(rec.holiday_worked_days, 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe manage.py test payroll.tests_holiday_record -v 2`
Expected: FAIL — unexpected keyword `holiday_pay`.

- [ ] **Step 3: Add fields**

Modify `payroll/models.py` — in `class PayrollRecord`, after `overtime_pay` in the Pay components block, add:
```python
    holiday_pay = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    holiday_days = models.PositiveIntegerField(default=0)
    holiday_worked_days = models.PositiveIntegerField(default=0)
```

Update `recalculate()` `gross_pay` computation to include `holiday_pay`:
```python
        self.gross_pay = (
            (self.basic_pay or zero) +
            (self.overtime_pay or zero) +
            (self.holiday_pay or zero) +
            (self.allowances or zero) +
            earning_adj
        ).quantize(Decimal('0.01'))
```

- [ ] **Step 4: Make and run migration**

Run:
```bash
./venv/Scripts/python.exe manage.py makemigrations payroll
./venv/Scripts/python.exe manage.py migrate
```
Expected: payroll migration created and applied.

- [ ] **Step 5: Run tests**

Run: `./venv/Scripts/python.exe manage.py test payroll.tests_holiday_record -v 2`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add payroll/models.py payroll/migrations payroll/tests_holiday_record.py
git commit -m "Add holiday_pay/holiday_days fields to PayrollRecord"
```

---

## Task 9: Payroll engine holiday pass

**Files:**
- Modify: `payroll/services.py`
- Create: `payroll/tests_holiday_engine.py`

- [ ] **Step 1: Write the failing test**

`payroll/tests_holiday_engine.py`:
```python
import datetime
from decimal import Decimal

from django.test import TestCase

from attendance.models import AttendanceRecord, WorkSchedule
from companies.models import Company
from employees.models import Employee
from holidays.models import Holiday
from holidays.constants import TYPE_REGULAR, TYPE_SPECIAL_NON_WORKING, SOURCE_COMPANY
from payroll.models import PayrollPeriod, PayrollRecord
from payroll.services import generate_payroll_for_period

D = datetime.date


def all_days_schedule(company):
    return WorkSchedule.objects.create(
        company=company, name="All Days", is_active=True,
        work_monday=True, work_tuesday=True, work_wednesday=True,
        work_thursday=True, work_friday=True, work_saturday=True, work_sunday=True,
        start_time=datetime.time(8, 0), end_time=datetime.time(17, 0),
    )


class HolidayEngineTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="HE", email="he@t.com")
        # Remove auto-seeded holidays so each test controls its own.
        Holiday.objects.filter(company=self.company).delete()
        self.ws = all_days_schedule(self.company)
        # Single-day period on a holiday date for precise assertions.
        self.period = PayrollPeriod.objects.create(
            company=self.company, name="Day", start_date=D(2026, 5, 1),
            end_date=D(2026, 5, 1))

    def _emp(self, pay_basis="daily", eid="E1"):
        return Employee.objects.create(
            company=self.company, employee_id=eid, first_name="A", last_name="B",
            email=f"{eid}@b.com", date_hired=D(2024, 1, 1), basic_salary=26000,
            work_schedule=self.ws, pay_basis=pay_basis,
        )

    def _record(self, emp):
        generate_payroll_for_period(self.period)
        return PayrollRecord.objects.get(payroll_period=self.period, employee=emp)

    def _reg_holiday(self, worked_mult=2, paid=True, pct=100):
        return Holiday.objects.create(
            company=self.company, name="Reg", date=D(2026, 5, 1),
            holiday_type=TYPE_REGULAR, source=SOURCE_COMPANY,
            is_paid=paid, no_work_pay_pct=pct, worked_multiplier=worked_mult)

    # daily_rate = 26000/26 = 1000.00

    def test_daily_regular_no_work_pays_one_day(self):
        emp = self._emp()
        self._reg_holiday()
        rec = self._record(emp)
        self.assertEqual(rec.holiday_pay, Decimal("1000.00"))
        self.assertEqual(rec.present_days, 0)
        self.assertEqual(rec.absent_days, Decimal("0"))   # holiday, not absence
        self.assertEqual(rec.basic_pay, Decimal("0.00"))
        self.assertEqual(rec.gross_pay, Decimal("1000.00"))
        self.assertEqual(rec.holiday_days, 1)
        self.assertEqual(rec.holiday_worked_days, 0)

    def test_daily_regular_worked_pays_double_no_double_base(self):
        emp = self._emp()
        self._reg_holiday(worked_mult=2)
        AttendanceRecord.objects.create(
            company=self.company, employee=emp, date=D(2026, 5, 1),
            time_in=datetime.time(8, 0), status="present", source="portal")
        rec = self._record(emp)
        self.assertEqual(rec.holiday_pay, Decimal("2000.00"))
        self.assertEqual(rec.present_days, 0)        # excluded from normal present
        self.assertEqual(rec.basic_pay, Decimal("0.00"))
        self.assertEqual(rec.gross_pay, Decimal("2000.00"))
        self.assertEqual(rec.holiday_worked_days, 1)

    def test_daily_special_nonworking_no_work_unpaid_by_default(self):
        emp = self._emp()
        Holiday.objects.create(
            company=self.company, name="SNW", date=D(2026, 5, 1),
            holiday_type=TYPE_SPECIAL_NON_WORKING, is_paid=False,
            no_work_pay_pct=0, worked_multiplier=Decimal("1.30"))
        rec = self._record(emp)
        self.assertEqual(rec.holiday_pay, Decimal("0.00"))
        self.assertEqual(rec.gross_pay, Decimal("0.00"))
        self.assertEqual(rec.absent_days, Decimal("0"))   # not counted as absent

    def test_daily_special_nonworking_worked_130(self):
        emp = self._emp()
        Holiday.objects.create(
            company=self.company, name="SNW", date=D(2026, 5, 1),
            holiday_type=TYPE_SPECIAL_NON_WORKING, is_paid=False,
            no_work_pay_pct=0, worked_multiplier=Decimal("1.30"))
        AttendanceRecord.objects.create(
            company=self.company, employee=emp, date=D(2026, 5, 1),
            time_in=datetime.time(8, 0), status="present", source="portal")
        rec = self._record(emp)
        self.assertEqual(rec.holiday_pay, Decimal("1300.00"))

    def test_monthly_special_nonworking_no_work_is_paid(self):
        emp = self._emp(pay_basis="monthly")
        Holiday.objects.create(
            company=self.company, name="SNW", date=D(2026, 5, 1),
            holiday_type=TYPE_SPECIAL_NON_WORKING, is_paid=False,
            no_work_pay_pct=100, worked_multiplier=Decimal("1.30"))
        rec = self._record(emp)
        # monthly basis: not docked -> paid full day even though default unpaid
        self.assertEqual(rec.holiday_pay, Decimal("1000.00"))

    def test_monthly_regular_worked_pays_double_once(self):
        emp = self._emp(pay_basis="monthly")
        self._reg_holiday(worked_mult=2)
        AttendanceRecord.objects.create(
            company=self.company, employee=emp, date=D(2026, 5, 1),
            time_in=datetime.time(8, 0), status="present", source="portal")
        rec = self._record(emp)
        self.assertEqual(rec.holiday_pay, Decimal("2000.00"))
        self.assertEqual(rec.basic_pay, Decimal("0.00"))
        self.assertEqual(rec.gross_pay, Decimal("2000.00"))
```

> NOTE on `monthly` no-work pct: for monthly basis the engine pays the day at
> `no_work_pay_pct` if set, else 100%. The test sets `no_work_pay_pct=100` to be
> explicit. The engine forces "paid" for monthly even when `is_paid=False`.

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe manage.py test payroll.tests_holiday_engine -v 2`
Expected: FAIL — `holiday_pay` always 0 (engine has no holiday pass yet).

- [ ] **Step 3: Implement the holiday pass**

Modify `payroll/services.py`:

(a) Add imports near the top (after existing imports):
```python
from decimal import Decimal, ROUND_HALF_UP  # ROUND_HALF_UP already imported; keep one
from holidays.services import build_exception_index, build_holiday_index, resolve_holiday
```
> Ensure no duplicate import of `Decimal`/`ROUND_HALF_UP`; the file already imports them — only add the `holidays.services` import line.

(b) Change `_calc_employee_payroll` signature and body. Replace the function with:
```python
def _calc_employee_payroll(emp, scheduled_dates, paid_leave_dates, unpaid_leave_dates,
                           att_by_date, holiday_resolver):
    """
    Compute payroll components for one employee.

    `holiday_resolver(emp, date)` returns effective holiday params dict or None.
    Holiday dates are handled in a dedicated pass and excluded from the normal
    present/absent classification so base pay is not double-counted.
    """
    salary = Decimal(str(emp.basic_salary or 0))
    daily_rate = (salary / _DAILY_DIVISOR).quantize(_Q4, rounding=ROUND_HALF_UP)
    hourly_rate = (daily_rate / _HOURS_PER_DAY).quantize(_Q4, rounding=ROUND_HALF_UP)
    is_monthly = getattr(emp, 'pay_basis', 'daily') == 'monthly'

    present_dates = set()
    absent_dates = set()
    late_min = 0
    undertime_min = 0
    overtime_min = 0

    holiday_pay = Decimal('0')
    holiday_days = 0
    holiday_worked_days = 0

    # Dates to evaluate for holidays: scheduled days plus any attended day.
    holiday_candidate_dates = set(scheduled_dates) | set(att_by_date.keys())

    for date in scheduled_dates:
        # Leave-covered → do not count toward present/absent
        if date in paid_leave_dates or date in unpaid_leave_dates:
            continue

        holiday = holiday_resolver(emp, date)
        if holiday is not None:
            # Handled in the holiday pass below; skip normal classification.
            continue

        att = att_by_date.get(date)
        if att and att.time_in is not None:
            present_dates.add(date)
            late_min += att.late_minutes or 0
            undertime_min += att.undertime_minutes or 0
            overtime_min += att.overtime_minutes or 0
        else:
            absent_dates.add(date)

    # ── Holiday pass ──────────────────────────────────────────────────────────
    for date in holiday_candidate_dates:
        # Leave-covered holidays are paid via leave, not here.
        if date in paid_leave_dates or date in unpaid_leave_dates:
            continue
        holiday = holiday_resolver(emp, date)
        if holiday is None:
            continue

        att = att_by_date.get(date)
        worked = bool(att and att.time_in is not None)
        is_scheduled = date in scheduled_dates

        if worked:
            holiday_days += 1
            holiday_worked_days += 1
            holiday_pay += daily_rate * Decimal(str(holiday['worked_multiplier']))
            # Worked-day late/UT/OT still apply.
            late_min += att.late_minutes or 0
            undertime_min += att.undertime_minutes or 0
            overtime_min += att.overtime_minutes or 0
        elif is_scheduled:
            # No-work holiday on a scheduled day.
            effective_paid = is_monthly or holiday['is_paid']
            if effective_paid:
                holiday_days += 1
                pct = Decimal(str(holiday['no_work_pay_pct']))
                holiday_pay += daily_rate * pct / Decimal('100')
        # else: rest-day, not worked → no pay.

    holiday_pay = holiday_pay.quantize(_Q2, rounding=ROUND_HALF_UP)

    scheduled_days = len(scheduled_dates)
    present_days = len(present_dates)
    paid_leave_days = Decimal(len(paid_leave_dates))
    unpaid_leave_days = Decimal(len(unpaid_leave_dates))
    absent_days = Decimal(len(absent_dates))
    payable_days = Decimal(present_days) + paid_leave_days

    basic_pay = (daily_rate * payable_days).quantize(_Q2, rounding=ROUND_HALF_UP)
    absence_ded = (daily_rate * absent_days).quantize(_Q2, rounding=ROUND_HALF_UP)

    late_ded = (
        Decimal(late_min) / Decimal(60) * hourly_rate
    ).quantize(_Q2, rounding=ROUND_HALF_UP)
    undertime_ded = (
        Decimal(undertime_min) / Decimal(60) * hourly_rate
    ).quantize(_Q2, rounding=ROUND_HALF_UP)
    ot_pay = (
        Decimal(overtime_min) / Decimal(60) * hourly_rate * _OT_MULTIPLIER
    ).quantize(_Q2, rounding=ROUND_HALF_UP)

    sss_ded = Decimal(str(emp.sss_contribution_amount or 0)).quantize(_Q2)
    philhealth_ded = Decimal(str(emp.philhealth_contribution_amount or 0)).quantize(_Q2)
    pagibig_ded = Decimal(str(emp.pagibig_contribution_amount or 0)).quantize(_Q2)
    tax_ded = Decimal(str(emp.tax_deduction_amount or 0)).quantize(_Q2)

    gross_pay = (basic_pay + ot_pay + holiday_pay).quantize(_Q2)
    total_ded = sss_ded + philhealth_ded + pagibig_ded + tax_ded + late_ded + undertime_ded
    net_pay = (gross_pay - total_ded).quantize(_Q2)

    return dict(
        scheduled_days=scheduled_days,
        present_days=present_days,
        paid_leave_days=paid_leave_days,
        unpaid_leave_days=unpaid_leave_days,
        absent_days=absent_days,
        payable_days=payable_days,
        late_minutes=late_min,
        undertime_minutes=undertime_min,
        overtime_minutes=overtime_min,
        daily_rate=daily_rate,
        hourly_rate=hourly_rate,
        basic_pay=basic_pay,
        overtime_pay=ot_pay,
        holiday_pay=holiday_pay,
        holiday_days=holiday_days,
        holiday_worked_days=holiday_worked_days,
        gross_pay=gross_pay,
        late_deduction=late_ded,
        undertime_deduction=undertime_ded,
        absence_deduction=absence_ded,
        sss_deduction=sss_ded,
        philhealth_deduction=philhealth_ded,
        pagibig_deduction=pagibig_ded,
        tax_deduction=tax_ded,
        net_pay=net_pay,
    )
```

(c) In `generate_payroll_for_period`, build the holiday/exception indexes and pass a resolver. After `att_map = _build_attendance_map(...)` add:
```python
    holiday_index = build_holiday_index(period.company, start_date, end_date)
    exception_index = build_exception_index(period.company)

    def _holiday_resolver(emp, date):
        return resolve_holiday(period.company, emp, date, holiday_index, exception_index)
```
And update the `_calc_employee_payroll(...)` call to pass it:
```python
        components = _calc_employee_payroll(
            emp,
            scheduled_sets.get(emp.pk, set()),
            paid_map.get(emp.pk, set()),
            unpaid_map.get(emp.pk, set()),
            att_map.get(emp.pk, {}),
            _holiday_resolver,
        )
```

- [ ] **Step 4: Run tests**

Run: `./venv/Scripts/python.exe manage.py test payroll.tests_holiday_engine -v 2`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add payroll/services.py payroll/tests_holiday_engine.py
git commit -m "Add holiday pass to payroll engine (holiday_pay, no double base)"
```

---

## Task 10: Audit & fix existing tests impacted by seeded holidays

**Files:**
- Modify (as needed): `payroll/tests.py`, `attendance/tests.py`, others surfaced by the run

- [ ] **Step 1: Run the full suite and capture failures**

Run: `./venv/Scripts/python.exe manage.py test -v 1`
Expected: New tests pass. Some pre-existing payroll/attendance tests may FAIL because
auto-seeded 2026 holidays (e.g. **Labor Day 2026-05-01**) now fall inside their
periods and add `holiday_pay` / change `present`/`absent` counts.

- [ ] **Step 2: For each failing test, choose the correct fix**

Apply, per failing test, the minimal correct fix:
- **Preferred (isolate intent):** if the test asserts non-holiday payroll math,
  disable holidays in its company so the test stays focused. Add at the start of
  the relevant `setUp`/test, after the company exists:
  ```python
  from holidays.models import Holiday
  Holiday.objects.filter(company=self.company).delete()
  ```
- **Alternative (assert new behavior):** if the test's period legitimately includes
  a worked/observed holiday and the new amount is correct, update the expected
  `present_days` / `absent_days` / `gross_pay` / `net_pay` values to include
  `holiday_pay`, and add a brief comment citing the holiday.

Document each change in the commit message.

- [ ] **Step 3: Re-run the full suite**

Run: `./venv/Scripts/python.exe manage.py test -v 1`
Expected: OK (0 failures).

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "Adjust existing payroll/attendance tests for seeded holidays"
```

---

## Task 11: Holiday management UI (views, urls, forms, templates, nav)

**Files:**
- Create: `holidays/forms.py`, `holidays/views.py`, `holidays/urls.py`
- Create: `templates/holidays/holiday_list.html`, `templates/holidays/holiday_form.html`, `templates/holidays/holiday_detail.html`, `templates/holidays/exception_form.html`, `templates/holidays/policy_form.html`
- Modify: `config/urls.py` (include), `templates/base.html` (nav link)
- Create: `holidays/tests/test_views.py`

- [ ] **Step 1: Write the failing test**

`holidays/tests/test_views.py`:
```python
import datetime

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from accounts.models import UserCompanyAccess, UserProfile
from companies.models import Company
from holidays.models import Holiday

D = datetime.date


class HolidayViewTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="V", email="v@t.com")
        self.admin = User.objects.create_superuser("admin", password="pass")
        self.client.login(username="admin", password="pass")
        session = self.client.session
        session["selected_company_id"] = self.company.pk
        session.save()

    def test_list_requires_login(self):
        self.client.logout()
        resp = self.client.get(reverse("holidays:holiday_list"))
        self.assertIn(resp.status_code, [302, 403])

    def test_list_shows_company_holidays(self):
        resp = self.client.get(reverse("holidays:holiday_list"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Labor Day")  # auto-seeded

    def test_toggle_enable_disable(self):
        h = Holiday.objects.filter(company=self.company).first()
        self.assertTrue(h.is_enabled)
        resp = self.client.post(reverse("holidays:holiday_toggle", args=[h.pk]))
        self.assertEqual(resp.status_code, 302)
        h.refresh_from_db()
        self.assertFalse(h.is_enabled)

    def test_add_custom_holiday(self):
        resp = self.client.post(reverse("holidays:holiday_add"), {
            "name": "Foundation Day", "date": "2026-07-15",
            "holiday_type": "company", "is_paid": "on",
            "no_work_pay_pct": "100", "worked_multiplier": "1.00",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Holiday.objects.filter(
            company=self.company, name="Foundation Day").exists())

    def test_company_scoping_blocks_other_company_holiday(self):
        other = Company.objects.create(name="Other", email="o@t.com")
        h = Holiday.objects.filter(company=other).first()
        resp = self.client.post(reverse("holidays:holiday_toggle", args=[h.pk]))
        self.assertIn(resp.status_code, [403, 404])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe manage.py test holidays.tests.test_views -v 2`
Expected: FAIL — `'holidays' is not a registered namespace`.

- [ ] **Step 3: Forms**

`holidays/forms.py`:
```python
from django import forms

from .models import CompanyHolidayPolicy, Holiday, HolidayException


class HolidayForm(forms.ModelForm):
    class Meta:
        model = Holiday
        fields = ["name", "date", "holiday_type", "is_enabled", "is_paid",
                  "no_work_pay_pct", "worked_multiplier", "notes"]
        widgets = {"date": forms.DateInput(attrs={"type": "date"})}


class HolidayExceptionForm(forms.ModelForm):
    class Meta:
        model = HolidayException
        fields = ["department", "employee", "not_observed",
                  "is_paid_override", "no_work_pay_pct_override",
                  "worked_multiplier_override"]

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        if company is not None:
            self.fields["department"].queryset = company.departments.all()
            self.fields["employee"].queryset = company.employees.all()


class CompanyHolidayPolicyForm(forms.ModelForm):
    class Meta:
        model = CompanyHolidayPolicy
        exclude = ["company", "created_at", "updated_at"]
```

- [ ] **Step 4: Views**

`holidays/views.py`:
```python
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.access import module_access_required
from accounts.company_access import get_selected_company_from_request, user_can_access_company

from .forms import CompanyHolidayPolicyForm, HolidayExceptionForm, HolidayForm
from .models import Holiday, HolidayException
from .seeding import get_or_create_policy

holiday_access = module_access_required("can_manage_payroll")


def _require_company(request):
    company = get_selected_company_from_request(request)
    if company is None:
        return None
    return company


def _get_company_holiday(request, pk):
    holiday = get_object_or_404(Holiday, pk=pk)
    if not user_can_access_company(request.user, holiday.company):
        raise PermissionDenied
    return holiday


@holiday_access
def holiday_list(request):
    company = _require_company(request)
    if company is None:
        messages.info(request, "Select a company to manage holidays.")
        return redirect("/")
    holidays = Holiday.objects.filter(company=company)
    type_filter = request.GET.get("type", "")
    if type_filter:
        holidays = holidays.filter(holiday_type=type_filter)
    return render(request, "holidays/holiday_list.html", {
        "holidays": holidays, "company": company, "type_filter": type_filter,
    })


@holiday_access
@require_POST
def holiday_toggle(request, pk):
    holiday = _get_company_holiday(request, pk)
    holiday.is_enabled = not holiday.is_enabled
    holiday.save(update_fields=["is_enabled"])
    messages.success(request, f'"{holiday.name}" {"enabled" if holiday.is_enabled else "disabled"}.')
    return redirect("holidays:holiday_list")


@holiday_access
def holiday_add(request):
    company = _require_company(request)
    if company is None:
        return redirect("/")
    form = HolidayForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        holiday = form.save(commit=False)
        holiday.company = company
        holiday.source = "company"
        holiday.save()
        messages.success(request, f'Holiday "{holiday.name}" added.')
        return redirect("holidays:holiday_list")
    return render(request, "holidays/holiday_form.html", {"form": form, "action": "Add"})


@holiday_access
def holiday_edit(request, pk):
    holiday = _get_company_holiday(request, pk)
    form = HolidayForm(request.POST or None, instance=holiday)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f'Holiday "{holiday.name}" updated.')
        return redirect("holidays:holiday_list")
    return render(request, "holidays/holiday_form.html", {"form": form, "action": "Edit"})


@holiday_access
def holiday_delete(request, pk):
    holiday = _get_company_holiday(request, pk)
    if request.method == "POST":
        holiday.delete()
        messages.success(request, "Holiday deleted.")
        return redirect("holidays:holiday_list")
    return render(request, "holidays/holiday_detail.html", {"holiday": holiday, "confirm_delete": True})


@holiday_access
def holiday_detail(request, pk):
    holiday = _get_company_holiday(request, pk)
    return render(request, "holidays/holiday_detail.html", {
        "holiday": holiday, "exceptions": holiday.exceptions.all(),
    })


@holiday_access
def exception_add(request, pk):
    holiday = _get_company_holiday(request, pk)
    form = HolidayExceptionForm(request.POST or None, company=holiday.company)
    if request.method == "POST" and form.is_valid():
        exc = form.save(commit=False)
        exc.holiday = holiday
        exc.full_clean()  # enforces exactly-one-target
        exc.save()
        messages.success(request, "Exception added.")
        return redirect("holidays:holiday_detail", pk=holiday.pk)
    return render(request, "holidays/exception_form.html", {"form": form, "holiday": holiday})


@holiday_access
@require_POST
def exception_delete(request, pk):
    exc = get_object_or_404(HolidayException, pk=pk)
    if not user_can_access_company(request.user, exc.holiday.company):
        raise PermissionDenied
    holiday_pk = exc.holiday_id
    exc.delete()
    messages.success(request, "Exception removed.")
    return redirect("holidays:holiday_detail", pk=holiday_pk)


@holiday_access
def policy_edit(request):
    company = _require_company(request)
    if company is None:
        return redirect("/")
    policy = get_or_create_policy(company)
    form = CompanyHolidayPolicyForm(request.POST or None, instance=policy)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Holiday policy updated.")
        return redirect("holidays:holiday_list")
    return render(request, "holidays/policy_form.html", {"form": form, "company": company})
```

- [ ] **Step 5: URLs**

`holidays/urls.py`:
```python
from django.urls import path

from . import views

app_name = "holidays"

urlpatterns = [
    path("", views.holiday_list, name="holiday_list"),
    path("add/", views.holiday_add, name="holiday_add"),
    path("policy/", views.policy_edit, name="policy_edit"),
    path("<int:pk>/", views.holiday_detail, name="holiday_detail"),
    path("<int:pk>/edit/", views.holiday_edit, name="holiday_edit"),
    path("<int:pk>/toggle/", views.holiday_toggle, name="holiday_toggle"),
    path("<int:pk>/delete/", views.holiday_delete, name="holiday_delete"),
    path("<int:pk>/exceptions/add/", views.exception_add, name="exception_add"),
    path("exceptions/<int:pk>/delete/", views.exception_delete, name="exception_delete"),
]
```

Modify `config/urls.py` — add inside `urlpatterns` after the portal include:
```python
    path('holidays/', include('holidays.urls')),
```

- [ ] **Step 6: Templates**

`templates/holidays/holiday_list.html`:
```html
{% extends 'base.html' %}
{% block title %}Holidays{% endblock %}
{% block page_title %}Holidays{% endblock %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-3">
  <div>
    <h5 class="mb-0">Holidays — {{ company.name }}</h5>
    <small class="text-muted">Enable/disable, set paid/unpaid and pay multipliers.</small>
  </div>
  <div>
    <a href="{% url 'holidays:policy_edit' %}" class="btn btn-outline-secondary btn-sm">
      <i class="bi bi-gear"></i> Pay Policy</a>
    <a href="{% url 'holidays:holiday_add' %}" class="btn btn-primary btn-sm">
      <i class="bi bi-plus-lg"></i> Add Holiday</a>
  </div>
</div>

<form method="get" class="mb-3">
  <select name="type" class="form-select form-select-sm w-auto d-inline"
          onchange="this.form.submit()">
    <option value="">All types</option>
    <option value="regular" {% if type_filter == 'regular' %}selected{% endif %}>Regular</option>
    <option value="special_non_working" {% if type_filter == 'special_non_working' %}selected{% endif %}>Special (Non-Working)</option>
    <option value="special_working" {% if type_filter == 'special_working' %}selected{% endif %}>Special (Working)</option>
    <option value="company" {% if type_filter == 'company' %}selected{% endif %}>Company</option>
    <option value="local" {% if type_filter == 'local' %}selected{% endif %}>Local</option>
  </select>
</form>

<div class="table-responsive">
<table class="table table-sm align-middle">
  <thead><tr>
    <th>Date</th><th>Name</th><th>Type</th><th>Paid</th>
    <th>No-work %</th><th>Worked ×</th><th>Status</th><th></th>
  </tr></thead>
  <tbody>
  {% for h in holidays %}
    <tr>
      <td>{{ h.date|date:"M d, Y" }}</td>
      <td><a href="{% url 'holidays:holiday_detail' h.pk %}">{{ h.name }}</a></td>
      <td>{{ h.get_holiday_type_display }}</td>
      <td>{% if h.is_paid %}<span class="badge bg-success">Paid</span>{% else %}<span class="badge bg-secondary">Unpaid</span>{% endif %}</td>
      <td>{{ h.no_work_pay_pct }}%</td>
      <td>{{ h.worked_multiplier }}×</td>
      <td>{% if h.is_enabled %}<span class="badge bg-primary">Enabled</span>{% else %}<span class="badge bg-light text-dark border">Disabled</span>{% endif %}</td>
      <td class="text-end">
        <form method="post" action="{% url 'holidays:holiday_toggle' h.pk %}" class="d-inline">
          {% csrf_token %}
          <button class="btn btn-outline-secondary btn-sm">{% if h.is_enabled %}Disable{% else %}Enable{% endif %}</button>
        </form>
        <a href="{% url 'holidays:holiday_edit' h.pk %}" class="btn btn-outline-primary btn-sm">Edit</a>
      </td>
    </tr>
  {% empty %}
    <tr><td colspan="8" class="text-center text-muted py-4">No holidays.</td></tr>
  {% endfor %}
  </tbody>
</table>
</div>
{% endblock %}
```

`templates/holidays/holiday_form.html`:
```html
{% extends 'base.html' %}
{% block title %}{{ action }} Holiday{% endblock %}
{% block page_title %}{{ action }} Holiday{% endblock %}
{% block content %}
<div class="card"><div class="card-body">
<form method="post">
  {% csrf_token %}
  {{ form.as_p }}
  <button class="btn btn-primary">Save</button>
  <a href="{% url 'holidays:holiday_list' %}" class="btn btn-outline-secondary">Cancel</a>
</form>
</div></div>
{% endblock %}
```

`templates/holidays/holiday_detail.html`:
```html
{% extends 'base.html' %}
{% block title %}{{ holiday.name }}{% endblock %}
{% block page_title %}{{ holiday.name }}{% endblock %}
{% block content %}
<p><a href="{% url 'holidays:holiday_list' %}" class="btn btn-outline-secondary btn-sm">&larr; Back</a></p>

{% if confirm_delete %}
<div class="alert alert-danger">
  Delete "{{ holiday.name }}"?
  <form method="post" action="{% url 'holidays:holiday_delete' holiday.pk %}" class="d-inline">
    {% csrf_token %}<button class="btn btn-danger btn-sm">Delete</button>
  </form>
</div>
{% endif %}

<div class="card mb-3"><div class="card-body">
  <p><strong>Date:</strong> {{ holiday.date }}</p>
  <p><strong>Type:</strong> {{ holiday.get_holiday_type_display }}</p>
  <p><strong>Paid:</strong> {{ holiday.is_paid|yesno }} · No-work {{ holiday.no_work_pay_pct }}% · Worked {{ holiday.worked_multiplier }}×</p>
</div></div>

<div class="d-flex justify-content-between align-items-center mb-2">
  <h6 class="mb-0">Exceptions (department / employee)</h6>
  <a href="{% url 'holidays:exception_add' holiday.pk %}" class="btn btn-sm btn-primary">Add exception</a>
</div>
<table class="table table-sm">
  <thead><tr><th>Target</th><th>Not observed</th><th>Overrides</th><th></th></tr></thead>
  <tbody>
  {% for exc in exceptions %}
    <tr>
      <td>{{ exc.employee|default:exc.department }}</td>
      <td>{{ exc.not_observed|yesno }}</td>
      <td>
        {% if exc.is_paid_override is not None %}paid={{ exc.is_paid_override|yesno }} {% endif %}
        {% if exc.no_work_pay_pct_override is not None %}nowork={{ exc.no_work_pay_pct_override }}% {% endif %}
        {% if exc.worked_multiplier_override is not None %}worked={{ exc.worked_multiplier_override }}×{% endif %}
      </td>
      <td class="text-end">
        <form method="post" action="{% url 'holidays:exception_delete' exc.pk %}" class="d-inline">
          {% csrf_token %}<button class="btn btn-outline-danger btn-sm">Remove</button>
        </form>
      </td>
    </tr>
  {% empty %}
    <tr><td colspan="4" class="text-muted text-center py-3">No exceptions.</td></tr>
  {% endfor %}
  </tbody>
</table>
{% endblock %}
```

`templates/holidays/exception_form.html`:
```html
{% extends 'base.html' %}
{% block title %}Add Exception{% endblock %}
{% block page_title %}Add Exception — {{ holiday.name }}{% endblock %}
{% block content %}
<div class="card"><div class="card-body">
<p class="text-muted">Set exactly one target: a department OR an employee.</p>
<form method="post">
  {% csrf_token %}
  {{ form.as_p }}
  <button class="btn btn-primary">Save</button>
  <a href="{% url 'holidays:holiday_detail' holiday.pk %}" class="btn btn-outline-secondary">Cancel</a>
</form>
</div></div>
{% endblock %}
```

`templates/holidays/policy_form.html`:
```html
{% extends 'base.html' %}
{% block title %}Holiday Pay Policy{% endblock %}
{% block page_title %}Holiday Pay Policy — {{ company.name }}{% endblock %}
{% block content %}
<div class="card"><div class="card-body">
<form method="post">
  {% csrf_token %}
  {{ form.as_p }}
  <button class="btn btn-primary">Save Policy</button>
  <a href="{% url 'holidays:holiday_list' %}" class="btn btn-outline-secondary">Cancel</a>
</form>
</div></div>
{% endblock %}
```

- [ ] **Step 7: Sidebar nav link**

Modify `templates/base.html` — inside the Finance `<ul>` (after the Payroll `<li>`, around line 449), add:
```html
      <li class="nav-item">
        <a href="{% url 'holidays:holiday_list' %}"
           class="nav-link {% if request.resolver_match.app_name == 'holidays' %}active{% endif %}">
          <i class="bi bi-calendar-event"></i> Holidays
        </a>
      </li>
```

- [ ] **Step 8: Run tests**

Run: `./venv/Scripts/python.exe manage.py test holidays.tests.test_views -v 2`
Expected: PASS (5 tests).

- [ ] **Step 9: Commit**

```bash
git add holidays config/urls.py templates/holidays templates/base.html
git commit -m "Add holidays management UI (list, toggle, add/edit, exceptions, policy)"
```

---

## Task 12: Payslip holiday line + full verification

**Files:**
- Modify: `templates/payroll/payslip.html` (earnings block ~ lines 355-384)
- Modify: `templates/payroll/payslip_email.html` (if it has an earnings table)

- [ ] **Step 1: Add the holiday-pay row to the payslip earnings table**

In `templates/payroll/payslip.html`, in the Earnings table after the overtime row
(around line 361) and before allowances/gross, add:
```html
          {% if record.holiday_pay %}
          <tr>
            <td>Holiday Pay{% if record.holiday_worked_days %} ({{ record.holiday_worked_days }} worked){% endif %}</td>
            <td class="amount">&#8369;{{ record.holiday_pay|floatformat:2 }}</td>
          </tr>
          {% endif %}
```
Apply the equivalent conditional row to `templates/payroll/payslip_email.html` if it
renders an earnings breakdown (match its existing markup for overtime).

- [ ] **Step 2: Manual render check (optional but recommended)**

Run: `./venv/Scripts/python.exe manage.py check`
Expected: no issues.

- [ ] **Step 3: Run the entire test suite**

Run: `./venv/Scripts/python.exe manage.py test -v 1`
Expected: OK — all tests pass (holidays + payroll + existing suite adjusted in Task 10).

- [ ] **Step 4: Run Django checks**

Run: `./venv/Scripts/python.exe manage.py check`
Expected: System check identified no issues.

- [ ] **Step 5: Commit**

```bash
git add templates/payroll/payslip.html templates/payroll/payslip_email.html
git commit -m "Show holiday pay line on payslip when > 0"
```

---

## Self-Review

**Spec coverage:**
- Default holidays preloaded → Task 1 (data) + Task 3/4/6 (seed).
- Enable/disable each default → `Holiday.is_enabled` + Task 11 toggle.
- Paid/unpaid per holiday → `Holiday.is_paid` + form.
- Pay rules/multipliers → `no_work_pay_pct`, `worked_multiplier`, `CompanyHolidayPolicy` (Task 2) + policy UI (Task 11).
- Company-created holidays → `source='company'` + `holiday_add` (Task 11).
- Dept/employee exceptions → `HolidayException` (Task 2) + resolution (Task 7) + UI (Task 11).
- Payroll respects holidays → Task 9; no double base verified by tests.
- Attendance/schedule untouched → engine only *reads* scheduled sets; no schedule edits. Verified by full suite (Task 10/12).
- Portal not broken → no portal files touched; full suite (Task 12).
- License untouched → no license files touched.
- Rules configurable (not hardcoded) → policy + per-holiday fields.
- Tests → Tasks 1,2,3,4,5,7,8,9,11 + suite (12).
- `pay_basis` daily default + explicit monthly tests → Task 2 + Task 9.
- Payslip shows holiday_pay if > 0 → Task 12.
- Auto-seed + command + migration → Tasks 4,5,6.

**Placeholder scan:** Task 1 notes an interim empty `signals.py` to keep the app importable before Task 4 fills it — explicit, not a placeholder. No TBD/TODO in code steps.

**Type consistency:** `resolve_holiday` returns dict with keys `holiday/is_paid/no_work_pay_pct/worked_multiplier` — consumed identically in Task 9. `build_holiday_index`/`build_exception_index` signatures match calls. `holiday_pay/holiday_days/holiday_worked_days` field names consistent across Tasks 8, 9, 12. Engine resolver signature `_holiday_resolver(emp, date)` matches `_calc_employee_payroll(..., holiday_resolver)` usage.
