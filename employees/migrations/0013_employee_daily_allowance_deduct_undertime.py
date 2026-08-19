from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('employees', '0012_employee_overtime_counting_rule'),
    ]

    operations = [
        migrations.AddField(
            model_name='employee',
            name='daily_allowance',
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                help_text='Allowance earned for each full day actually worked. Half-days receive half; absences receive none.',
                max_digits=10,
            ),
        ),
        migrations.AddField(
            model_name='employee',
            name='deduct_undertime',
            field=models.BooleanField(
                default=True,
                help_text='Deduct undertime from payroll. Undertime minutes remain recorded when disabled.',
            ),
        ),
    ]