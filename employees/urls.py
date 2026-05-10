from django.urls import path
from accounts.access import module_access_required
from . import views

app_name = 'employees'
employees_access = module_access_required('can_manage_employees')

urlpatterns = [
    # Employees
    path('', employees_access(views.employee_list), name='employee_list'),
    path('add/', employees_access(views.employee_add), name='employee_add'),
    path('<int:pk>/', employees_access(views.employee_detail), name='employee_detail'),
    path('<int:pk>/edit/', employees_access(views.employee_edit), name='employee_edit'),
    path('<int:pk>/delete/', employees_access(views.employee_delete), name='employee_delete'),

    # Departments
    path('departments/', employees_access(views.department_list), name='department_list'),
    path('departments/<int:pk>/edit/', employees_access(views.department_edit), name='department_edit'),
    path('departments/<int:pk>/delete/', employees_access(views.department_delete), name='department_delete'),

    # Positions
    path('positions/', employees_access(views.position_list), name='position_list'),
    path('positions/<int:pk>/edit/', employees_access(views.position_edit), name='position_edit'),
    path('positions/<int:pk>/delete/', employees_access(views.position_delete), name='position_delete'),
]
