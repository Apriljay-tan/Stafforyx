from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.db.models import Q, Count

from .models import Employee, Department, Position
from .forms import EmployeeForm, DepartmentForm, PositionForm


# ── Employees ─────────────────────────────────────────────────────────────────

def employee_list(request):
    qs = Employee.objects.select_related('company', 'department', 'position')

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

    context = {
        'employees': qs,
        'departments': Department.objects.all(),
        'q': q,
        'status_filter': status,
        'dept_filter': dept_id,
        'status_choices': Employee.STATUS_CHOICES,
    }
    return render(request, 'employees/employee_list.html', context)


def employee_detail(request, pk):
    employee = get_object_or_404(
        Employee.objects.select_related('company', 'department', 'position'),
        pk=pk,
    )
    return render(request, 'employees/employee_detail.html', {'employee': employee})


def employee_add(request):
    form = EmployeeForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        emp = form.save()
        messages.success(request, f'Employee {emp.full_name} added successfully.')
        return redirect('employees:employee_detail', pk=emp.pk)
    return render(request, 'employees/employee_form.html', {'form': form, 'action': 'Add'})


def employee_edit(request, pk):
    employee = get_object_or_404(Employee, pk=pk)
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
    if request.method == 'POST':
        name = employee.full_name
        employee.delete()
        messages.success(request, f'Employee "{name}" has been deleted.')
        return redirect('employees:employee_list')
    return render(request, 'employees/employee_confirm_delete.html', {'employee': employee})


# ── Departments ───────────────────────────────────────────────────────────────

def department_list(request):
    departments = Department.objects.select_related('company').annotate(
        employee_count=Count('employees')
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
    form = DepartmentForm(request.POST or None, instance=dept)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Department updated.')
        return redirect('employees:department_list')
    return render(request, 'employees/department_form.html', {'form': form, 'dept': dept})


def department_delete(request, pk):
    dept = get_object_or_404(Department, pk=pk)
    if request.method == 'POST':
        dept.delete()
        messages.success(request, 'Department deleted.')
        return redirect('employees:department_list')
    return render(request, 'employees/department_confirm_delete.html', {'dept': dept})


# ── Positions ─────────────────────────────────────────────────────────────────

def position_list(request):
    positions = Position.objects.select_related('company', 'department')
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
    form = PositionForm(request.POST or None, instance=pos)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Position updated.')
        return redirect('employees:position_list')
    return render(request, 'employees/position_form.html', {'form': form, 'pos': pos})


def position_delete(request, pk):
    pos = get_object_or_404(Position, pk=pk)
    if request.method == 'POST':
        pos.delete()
        messages.success(request, 'Position deleted.')
        return redirect('employees:position_list')
    return render(request, 'employees/position_confirm_delete.html', {'pos': pos})
