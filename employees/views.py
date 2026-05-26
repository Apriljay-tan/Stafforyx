from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Q, Count
from django.shortcuts import render, get_object_or_404, redirect

from accounts.company_access import filter_queryset_by_user_companies, user_can_access_company
from licenses.context_processors import get_license_state
from .models import Employee, Department, Position
from .forms import EmployeeForm, DepartmentForm, PositionForm


def _require_company_access(request, obj):
    """Raise 403 if the user cannot access obj.company."""
    if not user_can_access_company(request.user, obj.company):
        raise PermissionDenied

_LIMIT_MSG = (
    'Employee limit reached for your current license. '
    'Please upgrade your license to add more employees.'
)


# ── Employees ─────────────────────────────────────────────────────────────────

def employee_list(request):
    qs = Employee.objects.select_related('company', 'department', 'position')
    qs = filter_queryset_by_user_companies(qs, request.user)

    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(first_name__icontains=q) | Q(last_name__icontains=q) |
            Q(employee_id__icontains=q) | Q(email__icontains=q)
        )

    status = request.GET.get('status', '')
    if status:
        qs = qs.filter(status=status)

    dept_id = request.GET.get('department', '')
    if dept_id:
        qs = qs.filter(department_id=dept_id)

    state = get_license_state()
    total_employees = qs.count()
    max_employees   = state['max_employees']
    at_limit        = state['valid'] and max_employees > 0 and total_employees >= max_employees

    dept_qs = filter_queryset_by_user_companies(Department.objects.all(), request.user)
    context = {
        'employees':       qs,
        'departments':     dept_qs,
        'q':               q,
        'status_filter':   status,
        'dept_filter':     dept_id,
        'status_choices':  Employee.STATUS_CHOICES,
        'total_employees': total_employees,
        'max_employees':   max_employees,
        'at_limit':        at_limit,
    }
    return render(request, 'employees/employee_list.html', context)


def employee_detail(request, pk):
    employee = get_object_or_404(
        Employee.objects.select_related('company', 'department', 'position', 'work_schedule'),
        pk=pk,
    )
    _require_company_access(request, employee)
    return render(request, 'employees/employee_detail.html', {'employee': employee})


def employee_add(request):
    # Employee-limit check — uses only the verified signed payload
    state         = get_license_state()
    max_employees = state['max_employees']
    if state['valid'] and max_employees > 0:
        if Employee.objects.count() >= max_employees:
            messages.error(request, _LIMIT_MSG)
            return redirect('employees:employee_list')

    form = EmployeeForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        # Re-check on POST in case count changed between GET and form submission
        if state['valid'] and max_employees > 0 and Employee.objects.count() >= max_employees:
            messages.error(request, _LIMIT_MSG)
            return redirect('employees:employee_list')
        emp = form.save()
        messages.success(request, f'Employee {emp.full_name} added successfully.')
        return redirect('employees:employee_detail', pk=emp.pk)
    return render(request, 'employees/employee_form.html', {'form': form, 'action': 'Add'})


def employee_edit(request, pk):
    employee = get_object_or_404(Employee, pk=pk)
    _require_company_access(request, employee)
    form = EmployeeForm(request.POST or None, request.FILES or None, instance=employee)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Employee updated successfully.')
        return redirect('employees:employee_detail', pk=employee.pk)
    return render(request, 'employees/employee_form.html', {
        'form': form, 'employee': employee, 'action': 'Edit',
    })


def employee_delete(request, pk):
    employee = get_object_or_404(Employee, pk=pk)
    _require_company_access(request, employee)
    if request.method == 'POST':
        name = employee.full_name
        employee.delete()
        messages.success(request, f'Employee "{name}" has been deleted.')
        return redirect('employees:employee_list')
    return render(request, 'employees/employee_confirm_delete.html', {'employee': employee})


# ── Departments ───────────────────────────────────────────────────────────────

def department_list(request):
    departments = (
        filter_queryset_by_user_companies(Department.objects.all(), request.user)
        .select_related('company')
        .annotate(employee_count=Count('employees'))
    )
    form = DepartmentForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        dept = form.save()
        messages.success(request, f'Department "{dept.name}" created.')
        return redirect('employees:department_list')
    return render(request, 'employees/department_list.html', {
        'departments': departments,
        'form': form,
    })


def department_edit(request, pk):
    dept = get_object_or_404(Department, pk=pk)
    _require_company_access(request, dept)
    form = DepartmentForm(request.POST or None, instance=dept)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Department updated.')
        return redirect('employees:department_list')
    return render(request, 'employees/department_form.html', {'form': form, 'dept': dept})


def department_delete(request, pk):
    dept = get_object_or_404(Department, pk=pk)
    _require_company_access(request, dept)
    if request.method == 'POST':
        dept.delete()
        messages.success(request, 'Department deleted.')
        return redirect('employees:department_list')
    return render(request, 'employees/department_confirm_delete.html', {'dept': dept})


# ── Positions ─────────────────────────────────────────────────────────────────

def position_list(request):
    positions = (
        filter_queryset_by_user_companies(Position.objects.all(), request.user)
        .select_related('company', 'department')
    )
    form = PositionForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        pos = form.save()
        messages.success(request, f'Position "{pos.title}" created.')
        return redirect('employees:position_list')
    return render(request, 'employees/position_list.html', {
        'positions': positions,
        'form': form,
    })


def position_edit(request, pk):
    pos = get_object_or_404(Position, pk=pk)
    _require_company_access(request, pos)
    form = PositionForm(request.POST or None, instance=pos)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Position updated.')
        return redirect('employees:position_list')
    return render(request, 'employees/position_form.html', {'form': form, 'pos': pos})


def position_delete(request, pk):
    pos = get_object_or_404(Position, pk=pk)
    _require_company_access(request, pos)
    if request.method == 'POST':
        pos.delete()
        messages.success(request, 'Position deleted.')
        return redirect('employees:position_list')
    return render(request, 'employees/position_confirm_delete.html', {'pos': pos})
