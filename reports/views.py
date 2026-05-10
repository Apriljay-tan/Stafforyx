import csv

from django.http import HttpResponse
from django.shortcuts import render

from attendance.models import AttendanceRecord
from companies.models import Company
from documents.models import EmployeeDocument
from employees.models import Department, Employee
from leaves.models import LeaveRequest, LeaveType
from payroll.models import PayrollPeriod, PayrollRecord


def _csv_response(filename):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def _write_csv(filename, headers, rows):
    response = _csv_response(filename)
    writer = csv.writer(response)
    writer.writerow(headers)
    writer.writerows(rows)
    return response


def _employee_queryset(request):
    employees = Employee.objects.select_related('company', 'department', 'position')

    company_id = request.GET.get('company', '')
    if company_id:
        employees = employees.filter(company_id=company_id)

    status = request.GET.get('status', '')
    if status:
        employees = employees.filter(status=status)

    department_id = request.GET.get('department', '')
    if department_id:
        employees = employees.filter(department_id=department_id)

    return employees, {
        'company_filter': company_id,
        'status_filter': status,
        'department_filter': department_id,
    }


def _attendance_queryset(request):
    records = AttendanceRecord.objects.select_related('company', 'employee', 'employee__department')

    employee_id = request.GET.get('employee', '')
    if employee_id:
        records = records.filter(employee_id=employee_id)

    status = request.GET.get('status', '')
    if status:
        records = records.filter(status=status)

    date_from = request.GET.get('date_from', '')
    if date_from:
        records = records.filter(date__gte=date_from)

    date_to = request.GET.get('date_to', '')
    if date_to:
        records = records.filter(date__lte=date_to)

    return records, {
        'employee_filter': employee_id,
        'status_filter': status,
        'date_from_filter': date_from,
        'date_to_filter': date_to,
    }


def _leave_queryset(request):
    leave_requests = LeaveRequest.objects.select_related('company', 'employee', 'leave_type')

    employee_id = request.GET.get('employee', '')
    if employee_id:
        leave_requests = leave_requests.filter(employee_id=employee_id)

    status = request.GET.get('status', '')
    if status:
        leave_requests = leave_requests.filter(status=status)

    leave_type_id = request.GET.get('leave_type', '')
    if leave_type_id:
        leave_requests = leave_requests.filter(leave_type_id=leave_type_id)

    date_from = request.GET.get('date_from', '')
    if date_from:
        leave_requests = leave_requests.filter(start_date__gte=date_from)

    date_to = request.GET.get('date_to', '')
    if date_to:
        leave_requests = leave_requests.filter(end_date__lte=date_to)

    return leave_requests, {
        'employee_filter': employee_id,
        'status_filter': status,
        'leave_type_filter': leave_type_id,
        'date_from_filter': date_from,
        'date_to_filter': date_to,
    }


def _payroll_queryset(request):
    records = PayrollRecord.objects.select_related('company', 'payroll_period', 'employee')

    payroll_period_id = request.GET.get('payroll_period', '')
    if payroll_period_id:
        records = records.filter(payroll_period_id=payroll_period_id)

    employee_id = request.GET.get('employee', '')
    if employee_id:
        records = records.filter(employee_id=employee_id)

    status = request.GET.get('status', '')
    if status:
        records = records.filter(status=status)

    company_id = request.GET.get('company', '')
    if company_id:
        records = records.filter(company_id=company_id)

    return records, {
        'payroll_period_filter': payroll_period_id,
        'employee_filter': employee_id,
        'status_filter': status,
        'company_filter': company_id,
    }


def _documents_queryset(request):
    documents = EmployeeDocument.objects.select_related('company', 'employee', 'employee__department')

    employee_id = request.GET.get('employee', '')
    if employee_id:
        documents = documents.filter(employee_id=employee_id)

    document_type = request.GET.get('document_type', '')
    if document_type:
        documents = documents.filter(document_type=document_type)

    company_id = request.GET.get('company', '')
    if company_id:
        documents = documents.filter(company_id=company_id)

    return documents, {
        'employee_filter': employee_id,
        'document_type_filter': document_type,
        'company_filter': company_id,
    }


def reports_dashboard(request):
    context = {
        'employee_count': Employee.objects.count(),
        'attendance_count': AttendanceRecord.objects.count(),
        'leave_count': LeaveRequest.objects.count(),
        'payroll_count': PayrollRecord.objects.count(),
        'document_count': EmployeeDocument.objects.count(),
    }
    return render(request, 'reports/reports_dashboard.html', context)


def employee_report(request):
    employees, filters = _employee_queryset(request)
    context = {
        'employees': employees,
        'companies': Company.objects.all(),
        'departments': Department.objects.select_related('company'),
        'status_choices': Employee.STATUS_CHOICES,
        **filters,
    }
    return render(request, 'reports/employee_report.html', context)


def employee_report_export(request):
    employees, _filters = _employee_queryset(request)
    rows = [
        [
            employee.employee_id,
            employee.full_name,
            employee.email,
            employee.company.name,
            employee.department.name if employee.department else '',
            employee.position.title if employee.position else '',
            employee.get_status_display(),
            employee.date_hired,
            employee.basic_salary,
        ]
        for employee in employees
    ]
    return _write_csv(
        'employee_report.csv',
        ['Employee ID', 'Name', 'Email', 'Company', 'Department', 'Position', 'Status', 'Date Hired', 'Basic Salary'],
        rows,
    )


def attendance_report(request):
    records, filters = _attendance_queryset(request)
    context = {
        'records': records,
        'employees': Employee.objects.all().order_by('last_name', 'first_name'),
        'status_choices': AttendanceRecord.STATUS_CHOICES,
        **filters,
    }
    return render(request, 'reports/attendance_report.html', context)


def attendance_report_export(request):
    records, _filters = _attendance_queryset(request)
    rows = [
        [
            record.date,
            record.employee.employee_id,
            record.employee.full_name,
            record.time_in or '',
            record.time_out or '',
            record.total_hours,
            record.late_minutes,
            record.overtime_hours,
            record.get_status_display(),
        ]
        for record in records
    ]
    return _write_csv(
        'attendance_report.csv',
        ['Date', 'Employee ID', 'Employee', 'Time In', 'Time Out', 'Total Hours', 'Late Minutes', 'Overtime Hours', 'Status'],
        rows,
    )


def leave_report(request):
    leave_requests, filters = _leave_queryset(request)
    context = {
        'leave_requests': leave_requests,
        'employees': Employee.objects.all().order_by('last_name', 'first_name'),
        'leave_types': LeaveType.objects.select_related('company'),
        'status_choices': LeaveRequest.STATUS_CHOICES,
        **filters,
    }
    return render(request, 'reports/leave_report.html', context)


def leave_report_export(request):
    leave_requests, _filters = _leave_queryset(request)
    rows = [
        [
            leave_request.employee.employee_id,
            leave_request.employee.full_name,
            leave_request.leave_type.name,
            leave_request.start_date,
            leave_request.end_date,
            leave_request.total_days,
            leave_request.get_status_display(),
            leave_request.reason,
        ]
        for leave_request in leave_requests
    ]
    return _write_csv(
        'leave_report.csv',
        ['Employee ID', 'Employee', 'Leave Type', 'Start Date', 'End Date', 'Total Days', 'Status', 'Reason'],
        rows,
    )


def payroll_report(request):
    records, filters = _payroll_queryset(request)
    context = {
        'records': records,
        'payroll_periods': PayrollPeriod.objects.select_related('company'),
        'employees': Employee.objects.all().order_by('last_name', 'first_name'),
        'companies': Company.objects.all(),
        'status_choices': PayrollRecord.STATUS_CHOICES,
        **filters,
    }
    return render(request, 'reports/payroll_report.html', context)


def payroll_report_export(request):
    records, _filters = _payroll_queryset(request)
    rows = [
        [
            record.payroll_period.name,
            record.employee.employee_id,
            record.employee.full_name,
            record.company.name,
            record.basic_pay,
            record.allowances,
            record.overtime_pay,
            record.gross_pay,
            record.sss_deduction,
            record.philhealth_deduction,
            record.pagibig_deduction,
            record.tax_deduction,
            record.late_deduction,
            record.absence_deduction,
            record.other_deductions,
            record.net_pay,
            record.get_status_display(),
        ]
        for record in records
    ]
    return _write_csv(
        'payroll_report.csv',
        [
            'Payroll Period', 'Employee ID', 'Employee', 'Company', 'Basic Pay',
            'Allowances', 'Overtime Pay', 'Gross Pay', 'SSS Deduction',
            'PhilHealth Deduction', 'Pag-IBIG Deduction', 'Tax Deduction',
            'Late Deduction', 'Absence Deduction', 'Other Deductions', 'Net Pay', 'Status',
        ],
        rows,
    )


def documents_report(request):
    documents, filters = _documents_queryset(request)
    context = {
        'documents': documents,
        'employees': Employee.objects.all().order_by('last_name', 'first_name'),
        'companies': Company.objects.all(),
        'document_type_choices': EmployeeDocument.DOCUMENT_TYPE_CHOICES,
        **filters,
    }
    return render(request, 'reports/documents_report.html', context)


def documents_report_export(request):
    documents, _filters = _documents_queryset(request)
    rows = [
        [
            document.employee.employee_id,
            document.employee.full_name,
            document.company.name,
            document.title,
            document.get_document_type_display(),
            document.expiration_date or '',
            document.file.url if document.file else '',
            document.notes,
        ]
        for document in documents
    ]
    return _write_csv(
        'documents_report.csv',
        ['Employee ID', 'Employee', 'Company', 'Title', 'Document Type', 'Expiration Date', 'File URL', 'Notes'],
        rows,
    )
