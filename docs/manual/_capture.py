"""
One-off helper: log in to the local dev server and capture real screenshots
of each Stafforyx module for the user manual. Not wired into the app.

Run with the dev server already running on 127.0.0.1:8000:
    python docs/manual/_capture.py
"""
import os
import sys
import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.contrib.auth.models import User
from django.urls import reverse
from companies.models import Company
from employees.models import Employee
from payroll.models import PayrollRecord
from accounts.models import UserProfile

BASE = 'http://127.0.0.1:8000'
SHOT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'screenshots')
os.makedirs(SHOT_DIR, exist_ok=True)

USERNAME = '__manual_capture__'
PASSWORD = 'capture-pass-12345'


def ensure_capture_user():
    user, _ = User.objects.get_or_create(
        username=USERNAME,
        defaults={'is_staff': True, 'is_superuser': True},
    )
    user.is_staff = True
    user.is_superuser = True
    user.set_password(PASSWORD)
    user.save()
    # Link to an employee so the Employee Portal renders real data.
    emp = Employee.objects.first()
    UserProfile.objects.update_or_create(
        user=user,
        defaults={'role': 'super_admin', 'is_active_stafforyx': True, 'employee': emp},
    )
    return user


def safe_reverse(name, *args):
    try:
        return reverse(name, args=args)
    except Exception:
        return None


def build_targets():
    company = Company.objects.first()
    employee = Employee.objects.first()
    record = PayrollRecord.objects.first()

    t = []
    # (label, path, full_page)
    t.append(('02_dashboard', '/', True))
    t.append(('03_employees', safe_reverse('employees:employee_list'), True))
    if employee:
        t.append(('04_employee_detail', safe_reverse('employees:employee_detail', employee.pk), True))
    t.append(('05_attendance', safe_reverse('attendance:attendance_list'), True))
    t.append(('06_schedules', safe_reverse('attendance:schedule_list'), True))
    t.append(('07_leaves', safe_reverse('leaves:leave_request_list'), True))
    t.append(('08_payroll', safe_reverse('payroll:payroll_record_list'), True))
    t.append(('09_payroll_generate', safe_reverse('payroll:payroll_generate'), True))
    if record:
        t.append(('10_payslip', safe_reverse('payroll:payslip_view', record.pk), True))
    t.append(('11_holidays', safe_reverse('holidays:holiday_list'), True))
    t.append(('12_documents', safe_reverse('documents:employee_document_list'), True))
    t.append(('13_announcements', safe_reverse('announcements:announcement_list'), True))
    t.append(('14_reports', safe_reverse('reports:reports_dashboard'), True))
    t.append(('15_overtime', safe_reverse('overtime:manage_overtime'), True))
    t.append(('16_users', safe_reverse('accounts:user_list'), True))
    t.append(('17_theme', safe_reverse('accounts:theme'), True))
    if company:
        t.append(('18_payslip_settings', safe_reverse('companies:payslip_settings', company.pk), True))
    t.append(('19_license', safe_reverse('licenses:license_status'), True))
    t.append(('20_portal', safe_reverse('portal:dashboard'), True))
    t.append(('21_portal_payslips', safe_reverse('portal:payslip_list'), True))
    return [(label, BASE + path, fp) for (label, path, fp) in t if path]


def main():
    from playwright.sync_api import sync_playwright

    ensure_capture_user()
    targets = build_targets()
    captured = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={'width': 1440, 'height': 900},
                                  device_scale_factor=2)
        page = ctx.new_page()

        # Login page screenshot (logged out)
        page.goto(BASE + '/accounts/login/', wait_until='networkidle')
        page.wait_for_timeout(700)
        p1 = os.path.join(SHOT_DIR, '01_login.png')
        page.screenshot(path=p1)
        captured.append('01_login')

        # Perform login
        page.fill('input[name="username"]', USERNAME)
        page.fill('input[name="password"]', PASSWORD)
        page.click('button[type="submit"], input[type="submit"]')
        page.wait_for_load_state('networkidle')
        page.wait_for_timeout(700)

        for label, url, full_page in targets:
            try:
                page.goto(url, wait_until='networkidle', timeout=20000)
                page.wait_for_timeout(900)  # let fonts/CDN + animations settle
                path = os.path.join(SHOT_DIR, label + '.png')
                page.screenshot(path=path, full_page=full_page)
                captured.append(label)
                print('  captured', label)
            except Exception as e:
                print('  FAILED', label, '->', type(e).__name__, str(e)[:80])

        browser.close()

    print('Total captured:', len(captured))


if __name__ == '__main__':
    main()
