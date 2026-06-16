import datetime
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.urls import reverse

from accounts.models import UserCompanyAccess, UserProfile
from attendance.models import AttendanceRecord, WorkSchedule
from companies.models import Company
from employees.models import Employee
from notifications.models import Notification
from payroll.models import PayrollAdjustment, PayrollPeriod, PayrollRecord
from payroll.services import generate_payroll_for_period

from .models import CashAdvanceRequest

_RELEASE_DATE = datetime.date(2026, 6, 30)
_counter = 0


def _company(name='CA Co'):
    return Company.objects.create(name=name)


def _employee(company, user=None, emp_id=None):
    global _counter
    _counter += 1
    return Employee.objects.create(
        company=company,
        user=user,
        employee_id=emp_id or f'CA{_counter:03d}',
        first_name='Cash',
        last_name=f'Advance{_counter}',
        email=f'ca{_counter}@test.com',
        date_hired=datetime.date(2024, 1, 1),
        status='active',
    )


def _ca(company, employee, **kwargs):
    defaults = dict(
        company=company, employee=employee,
        amount=Decimal('1000.00'), reason='Need funds',
        status=CashAdvanceRequest.STATUS_PENDING,
    )
    defaults.update(kwargs)
    return CashAdvanceRequest.objects.create(**defaults)


def _hr_user(company, username='hr', *, can_manage_payroll=True,
             can_manage_employees=False, role='hr_admin'):
    user = User.objects.create_user(username, password='pw')
    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.role = role
    profile.can_manage_payroll = can_manage_payroll
    profile.can_manage_employees = can_manage_employees
    profile.is_active_stafforyx = True
    profile.save()
    UserCompanyAccess.objects.create(user=user, company=company, is_active=True)
    return user


# ── Employee portal: create / view / ownership ────────────────────────────────

class PortalCashAdvanceTests(TestCase):
    def setUp(self):
        self.company = _company()
        self.user = User.objects.create_user('emp1', password='pw')
        self.emp = _employee(self.company, user=self.user)
        self.client.force_login(self.user)

    def test_list_page_loads_with_request_button(self):
        resp = self.client.get(reverse('portal:ca_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Request Cash Advance')

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_employee_can_create_own_ca_request(self, _mock_license):
        resp = self.client.post(reverse('portal:ca_new'), {
            'amount': '1500.00',
            'reason': 'Medical bill',
            'requested_release_date': _RELEASE_DATE.isoformat(),
        })
        self.assertEqual(resp.status_code, 302)
        ca = CashAdvanceRequest.objects.get(employee=self.emp)
        self.assertEqual(ca.status, CashAdvanceRequest.STATUS_PENDING)
        self.assertEqual(ca.company, self.company)
        self.assertEqual(ca.amount, Decimal('1500.00'))
        self.assertEqual(ca.requested_release_date, _RELEASE_DATE)

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_release_date_is_optional(self, _mock_license):
        resp = self.client.post(reverse('portal:ca_new'), {
            'amount': '500.00',
            'reason': 'Groceries',
        })
        self.assertEqual(resp.status_code, 302)
        ca = CashAdvanceRequest.objects.get(employee=self.emp)
        self.assertIsNone(ca.requested_release_date)

    def test_employee_can_view_own_ca_requests(self):
        _ca(self.company, self.emp, reason='My very own CA')
        resp = self.client.get(reverse('portal:ca_list'))
        self.assertContains(resp, 'My very own CA')

    def test_employee_cannot_view_other_employee_ca_requests(self):
        other = _employee(self.company)
        _ca(self.company, other, reason='Someone elses CA')
        resp = self.client.get(reverse('portal:ca_list'))
        self.assertNotContains(resp, 'Someone elses CA')

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_employee_cannot_edit_released_request(self, _mock_license):
        ca = _ca(
            self.company, self.emp, amount=Decimal('1000.00'),
            status=CashAdvanceRequest.STATUS_RELEASED,
        )
        # GET edit page should bounce back to the list.
        resp = self.client.get(reverse('portal:ca_edit', args=[ca.pk]), follow=True)
        self.assertContains(resp, 'can no longer be edited')
        # POST edit must not change the amount.
        self.client.post(reverse('portal:ca_edit', args=[ca.pk]), {
            'amount': '9999.00', 'reason': 'hax',
        })
        ca.refresh_from_db()
        self.assertEqual(ca.amount, Decimal('1000.00'))
        self.assertEqual(ca.status, CashAdvanceRequest.STATUS_RELEASED)

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_employee_can_edit_pending_request(self, _mock_license):
        ca = _ca(self.company, self.emp, amount=Decimal('1000.00'))
        self.client.post(reverse('portal:ca_edit', args=[ca.pk]), {
            'amount': '1200.00', 'reason': 'updated reason',
        })
        ca.refresh_from_db()
        self.assertEqual(ca.amount, Decimal('1200.00'))

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_employee_cannot_edit_another_employees_request(self, _mock_license):
        other = _employee(self.company)
        ca = _ca(self.company, other, amount=Decimal('1000.00'))
        resp = self.client.post(reverse('portal:ca_edit', args=[ca.pk]), {
            'amount': '5000.00', 'reason': 'theft',
        })
        self.assertEqual(resp.status_code, 404)
        ca.refresh_from_db()
        self.assertEqual(ca.amount, Decimal('1000.00'))

    def test_unlinked_user_sees_friendly_message(self):
        lone = User.objects.create_user('lone', password='pw')
        self.client.force_login(lone)
        resp = self.client.get(reverse('portal:ca_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'portal/no_employee.html')


# ── HR/Admin management: scoping, approve, reject, release, permissions ────────

class ManageCashAdvanceTests(TestCase):
    def setUp(self):
        self.company = _company('Scope Co')
        self.other = _company('Other Co')
        self.emp = _employee(self.company)
        self.ca = _ca(self.company, self.emp, reason='In scope CA')

    def test_hr_sees_only_company_scoped_requests(self):
        other_emp = _employee(self.other)
        _ca(self.other, other_emp, reason='Out of scope CA')

        hr = _hr_user(self.company)
        self.client.force_login(hr)
        resp = self.client.get(reverse('cash_advance:manage_ca') + '?tab=history')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.emp.last_name)
        self.assertNotContains(resp, other_emp.last_name)

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_hr_can_approve_request(self, _mock_license):
        hr = _hr_user(self.company)
        self.client.force_login(hr)
        resp = self.client.post(
            reverse('cash_advance:manage_ca_detail', args=[self.ca.pk]),
            {'action': 'approve', 'manager_note': 'ok'},
        )
        self.assertEqual(resp.status_code, 302)
        self.ca.refresh_from_db()
        self.assertEqual(self.ca.status, CashAdvanceRequest.STATUS_APPROVED)
        self.assertEqual(self.ca.approved_by, hr)
        self.assertIsNotNone(self.ca.approved_at)

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_hr_can_reject_request(self, _mock_license):
        hr = _hr_user(self.company)
        self.client.force_login(hr)
        self.client.post(
            reverse('cash_advance:manage_ca_detail', args=[self.ca.pk]),
            {'action': 'reject'},
        )
        self.ca.refresh_from_db()
        self.assertEqual(self.ca.status, CashAdvanceRequest.STATUS_REJECTED)
        self.assertEqual(self.ca.rejected_by, hr)
        self.assertIsNotNone(self.ca.rejected_at)

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_hr_can_cancel_request(self, _mock_license):
        hr = _hr_user(self.company)
        self.client.force_login(hr)
        self.client.post(
            reverse('cash_advance:manage_ca_detail', args=[self.ca.pk]),
            {'action': 'cancel', 'cancel_reason': 'duplicate'},
        )
        self.ca.refresh_from_db()
        self.assertEqual(self.ca.status, CashAdvanceRequest.STATUS_CANCELLED)

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_authorized_user_can_mark_released(self, _mock_license):
        self.ca.status = CashAdvanceRequest.STATUS_APPROVED
        self.ca.save(update_fields=['status'])
        payroll = _hr_user(self.company, username='payroll', can_manage_payroll=True)
        self.client.force_login(payroll)
        self.client.post(
            reverse('cash_advance:manage_ca_detail', args=[self.ca.pk]),
            {'action': 'release', 'release_note': 'cash handed over'},
        )
        self.ca.refresh_from_db()
        self.assertEqual(self.ca.status, CashAdvanceRequest.STATUS_RELEASED)
        self.assertEqual(self.ca.released_by, payroll)
        self.assertIsNotNone(self.ca.released_at)
        self.assertEqual(self.ca.release_note, 'cash handed over')

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_non_payroll_manager_cannot_release(self, _mock_license):
        self.ca.status = CashAdvanceRequest.STATUS_APPROVED
        self.ca.save(update_fields=['status'])
        # HR with employee-management only — may manage but not release money.
        hr = _hr_user(
            self.company, username='hronly',
            can_manage_payroll=False, can_manage_employees=True,
        )
        self.client.force_login(hr)
        resp = self.client.post(
            reverse('cash_advance:manage_ca_detail', args=[self.ca.pk]),
            {'action': 'release', 'release_note': 'should fail'},
        )
        self.assertEqual(resp.status_code, 403)
        self.ca.refresh_from_db()
        self.assertEqual(self.ca.status, CashAdvanceRequest.STATUS_APPROVED)

    def test_unauthorized_user_cannot_access_management(self):
        plain = User.objects.create_user('plain', password='pw')
        self.client.force_login(plain)
        resp = self.client.get(reverse('cash_advance:manage_ca'))
        self.assertEqual(resp.status_code, 403)

    def test_hr_cannot_open_out_of_scope_detail(self):
        other_emp = _employee(self.other)
        other_ca = _ca(self.other, other_emp)
        hr = _hr_user(self.company)
        self.client.force_login(hr)
        resp = self.client.get(
            reverse('cash_advance:manage_ca_detail', args=[other_ca.pk])
        )
        self.assertEqual(resp.status_code, 403)

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_history_single_delete_removes_visible_cash_advance_and_notification(self, _mock_license):
        self.ca.status = CashAdvanceRequest.STATUS_REJECTED
        self.ca.save(update_fields=['status'])
        hr = _hr_user(self.company)
        Notification.objects.create(
            recipient=hr,
            company=self.company,
            notification_type=Notification.TYPE_CASH_ADVANCE_REQUEST,
            title='Old CA',
            message='Old cash advance.',
            content_type=ContentType.objects.get_for_model(self.ca, for_concrete_model=False),
            object_id=self.ca.pk,
        )

        self.client.force_login(hr)
        response = self.client.post(
            reverse('cash_advance:manage_ca') + '?tab=history',
            {'action': 'delete_selected', 'selected_ids': [str(self.ca.pk)]},
        )

        self.assertRedirects(
            response,
            reverse('cash_advance:manage_ca') + '?tab=history',
            fetch_redirect_response=False,
        )
        self.assertFalse(CashAdvanceRequest.objects.filter(pk=self.ca.pk).exists())
        self.assertFalse(Notification.objects.filter(object_id=self.ca.pk).exists())

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_history_bulk_delete_is_scoped_to_accessible_companies(self, _mock_license):
        other_emp = _employee(self.other)
        other_ca = _ca(self.other, other_emp, status=CashAdvanceRequest.STATUS_REJECTED)
        self.ca.status = CashAdvanceRequest.STATUS_CANCELLED
        self.ca.save(update_fields=['status'])
        hr = _hr_user(self.company)

        self.client.force_login(hr)
        response = self.client.post(
            reverse('cash_advance:manage_ca') + '?tab=history',
            {
                'action': 'delete_selected',
                'selected_ids': [str(self.ca.pk), str(other_ca.pk)],
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(CashAdvanceRequest.objects.filter(pk=self.ca.pk).exists())
        self.assertTrue(CashAdvanceRequest.objects.filter(pk=other_ca.pk).exists())

    @patch('licenses.middleware.is_license_active', return_value=True)
    def test_cash_advance_delete_is_ignored_outside_history_tab(self, _mock_license):
        hr = _hr_user(self.company)

        self.client.force_login(hr)
        response = self.client.post(
            reverse('cash_advance:manage_ca') + '?tab=pending',
            {'action': 'delete_selected', 'selected_ids': [str(self.ca.pk)]},
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(CashAdvanceRequest.objects.filter(pk=self.ca.pk).exists())


# ── Phase 6C: payroll deduction integration ───────────────────────────────────

_MON = datetime.date(2025, 5, 19)   # Monday
_DAYS = [_MON + datetime.timedelta(days=i) for i in range(5)]  # Mon–Fri


class CashAdvanceDeductionTests(TestCase):
    """Released cash advances flow into payroll as deduction lines."""

    def setUp(self):
        self.company = _company('Deduct Co')
        self.schedule = WorkSchedule.objects.create(
            company=self.company, name='Std',
            start_time=datetime.time(8, 0), end_time=datetime.time(17, 0),
            grace_minutes=15,
            work_monday=True, work_tuesday=True, work_wednesday=True,
            work_thursday=True, work_friday=True, is_active=True,
        )
        self.emp = Employee.objects.create(
            company=self.company, employee_id='DED1',
            first_name='Dee', last_name='Ducted', email='dee@test.com',
            date_hired=datetime.date(2020, 1, 1),
            basic_salary=Decimal('26000.00'),  # daily 1000 → 5 days = 5000 net
            work_schedule=self.schedule, status='active',
        )
        self.period = PayrollPeriod.objects.create(
            company=self.company, name='May 19-23 2025',
            start_date=_DAYS[0], end_date=_DAYS[-1],
        )

    # helpers ------------------------------------------------------------------
    def _present_all(self):
        for d in _DAYS:
            AttendanceRecord.objects.create(
                company=self.company, employee=self.emp, date=d,
                time_in=datetime.time(8, 0), status='present',
            )

    def _released_ca(self, amount):
        return _ca(
            self.company, self.emp, amount=Decimal(amount),
            status=CashAdvanceRequest.STATUS_RELEASED,
        )

    def _record(self):
        return PayrollRecord.objects.get(payroll_period=self.period, employee=self.emp)

    def _ca_lines(self, ca):
        return PayrollAdjustment.objects.filter(source_cash_advance=ca)

    # 1. approved (not released) CA is not deducted -----------------------------
    def test_approved_ca_is_not_deducted(self):
        self._present_all()
        ca = _ca(self.company, self.emp, amount=Decimal('1000.00'),
                 status=CashAdvanceRequest.STATUS_APPROVED)
        generate_payroll_for_period(self.period)
        rec = self._record()
        self.assertFalse(self._ca_lines(ca).exists())
        self.assertEqual(rec.net_pay, Decimal('5000.00'))

    # 2 & 3 & 5. released CA deducted, appears on record, reduces net -----------
    def test_released_ca_is_deducted_in_next_payroll(self):
        self._present_all()
        ca = self._released_ca('1000.00')
        generate_payroll_for_period(self.period)
        rec = self._record()

        line = self._ca_lines(ca).get()
        self.assertEqual(line.payroll_record, rec)
        self.assertEqual(line.adjustment_type, 'deduction')
        self.assertEqual(line.name, 'Cash Advance')
        self.assertEqual(line.amount, Decimal('1000.00'))
        # net pay subtracts the CA
        self.assertEqual(rec.net_pay, Decimal('4000.00'))

    # 4. CA deduction appears in payslip context/template ----------------------
    def test_ca_deduction_appears_in_payslip(self):
        self._present_all()
        self._released_ca('1000.00')
        generate_payroll_for_period(self.period)
        rec = self._record()

        admin = User.objects.create_superuser('ca-admin', 'ca-admin@test.com', 'pw')
        self.client.force_login(admin)
        resp = self.client.get(reverse('payroll:payslip_view', args=[rec.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Cash Advance')
        names = [a.name for a in resp.context['deduction_adjs']]
        self.assertIn('Cash Advance', names)

    # 6. partial deduction leaves a remaining balance --------------------------
    def test_partial_deduction_leaves_remaining_balance(self):
        self._present_all()                      # net pay 5000
        ca = self._released_ca('7000.00')        # bigger than net pay
        generate_payroll_for_period(self.period)
        rec = self._record()

        line = self._ca_lines(ca).get()
        self.assertEqual(line.amount, Decimal('5000.00'))   # capped by net pay
        self.assertEqual(rec.net_pay, Decimal('0.00'))
        ca.refresh_from_db()
        self.assertEqual(ca.total_deducted_amount, Decimal('5000.00'))
        self.assertEqual(ca.remaining_balance, Decimal('2000.00'))
        self.assertEqual(ca.deduction_status, CashAdvanceRequest.DEDUCTION_SCHEDULED)

    # 7. full deduction marks CA as deducted / paid off ------------------------
    def test_full_deduction_marks_ca_deducted(self):
        self._present_all()
        ca = self._released_ca('1000.00')
        generate_payroll_for_period(self.period)
        ca.refresh_from_db()
        self.assertEqual(ca.remaining_balance, Decimal('0.00'))
        self.assertEqual(ca.deduction_status, CashAdvanceRequest.DEDUCTION_DEDUCTED)
        self.assertIsNotNone(ca.fully_deducted_at)

    # 8. regenerating draft payroll does not duplicate the deduction -----------
    def test_regenerate_does_not_double_deduct(self):
        self._present_all()
        ca = self._released_ca('1000.00')
        generate_payroll_for_period(self.period)
        generate_payroll_for_period(self.period)   # regenerate draft
        generate_payroll_for_period(self.period)   # and again

        self.assertEqual(self._ca_lines(ca).count(), 1)
        rec = self._record()
        self.assertEqual(rec.net_pay, Decimal('4000.00'))
        ca.refresh_from_db()
        self.assertEqual(ca.total_deducted_amount, Decimal('1000.00'))

    # 9. payroll officer can defer/revoke before finalization ------------------
    def test_payroll_officer_can_defer_deduction(self):
        self._present_all()
        ca = self._released_ca('1000.00')
        generate_payroll_for_period(self.period)
        line = self._ca_lines(ca).get()

        officer = _hr_user(self.company, username='officer', can_manage_payroll=True)
        self.client.force_login(officer)
        with patch('licenses.middleware.is_license_active', return_value=True):
            resp = self.client.post(
                reverse('cash_advance:manage_ca_detail', args=[ca.pk]),
                {'action': 'revoke_deduction', 'adjustment_id': line.pk},
            )
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(self._ca_lines(ca).exists())
        ca.refresh_from_db()
        self.assertEqual(ca.total_deducted_amount, Decimal('0.00'))
        self.assertEqual(ca.remaining_balance, Decimal('1000.00'))
        self.assertEqual(ca.deduction_status, CashAdvanceRequest.DEDUCTION_RELEASED)
        self.assertEqual(self._record().net_pay, Decimal('5000.00'))

    def test_payroll_officer_can_adjust_deduction_amount(self):
        self._present_all()
        ca = self._released_ca('1000.00')
        generate_payroll_for_period(self.period)
        line = self._ca_lines(ca).get()

        officer = _hr_user(self.company, username='officer2', can_manage_payroll=True)
        self.client.force_login(officer)
        with patch('licenses.middleware.is_license_active', return_value=True):
            self.client.post(
                reverse('cash_advance:manage_ca_detail', args=[ca.pk]),
                {'action': 'adjust_deduction', 'adjustment_id': line.pk, 'amount': '400.00'},
            )
        ca.refresh_from_db()
        self.assertEqual(ca.total_deducted_amount, Decimal('400.00'))
        self.assertEqual(ca.remaining_balance, Decimal('600.00'))
        self.assertEqual(self._record().net_pay, Decimal('4600.00'))

    def test_non_payroll_user_cannot_defer_deduction(self):
        self._present_all()
        ca = self._released_ca('1000.00')
        generate_payroll_for_period(self.period)
        line = self._ca_lines(ca).get()

        hr = _hr_user(self.company, username='hronly',
                      can_manage_payroll=False, can_manage_employees=True)
        self.client.force_login(hr)
        with patch('licenses.middleware.is_license_active', return_value=True):
            resp = self.client.post(
                reverse('cash_advance:manage_ca_detail', args=[ca.pk]),
                {'action': 'revoke_deduction', 'adjustment_id': line.pk},
            )
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(self._ca_lines(ca).exists())

    # 10. company scoping prevents cross-company deduction ---------------------
    def test_company_scoping_prevents_cross_company_deduction(self):
        self._present_all()
        ca = self._released_ca('1000.00')   # company A advance

        # A separate company + employee + period; generating its payroll must
        # never touch company A's cash advance.
        other_co = _company('Other Deduct Co')
        other_sched = WorkSchedule.objects.create(
            company=other_co, name='Std',
            start_time=datetime.time(8, 0), end_time=datetime.time(17, 0),
            grace_minutes=15,
            work_monday=True, work_tuesday=True, work_wednesday=True,
            work_thursday=True, work_friday=True, is_active=True,
        )
        other_emp = Employee.objects.create(
            company=other_co, employee_id='OD1',
            first_name='Bee', last_name='Other', email='bee@test.com',
            date_hired=datetime.date(2020, 1, 1),
            basic_salary=Decimal('26000.00'),
            work_schedule=other_sched, status='active',
        )
        for d in _DAYS:
            AttendanceRecord.objects.create(
                company=other_co, employee=other_emp, date=d,
                time_in=datetime.time(8, 0), status='present',
            )
        other_period = PayrollPeriod.objects.create(
            company=other_co, name='May 19-23 2025',
            start_date=_DAYS[0], end_date=_DAYS[-1],
        )
        generate_payroll_for_period(other_period)

        other_rec = PayrollRecord.objects.get(
            payroll_period=other_period, employee=other_emp
        )
        # Other company's payroll has no CA deduction.
        self.assertFalse(other_rec.adjustments.filter(source_cash_advance__isnull=False).exists())
        self.assertEqual(other_rec.net_pay, Decimal('5000.00'))
        # Company A advance remains untouched.
        ca.refresh_from_db()
        self.assertEqual(ca.total_deducted_amount, Decimal('0.00'))
        self.assertFalse(self._ca_lines(ca).exists())
