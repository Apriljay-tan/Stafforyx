from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('companies', '0005_company_payslip_prepared_by_name_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='company',
            name='attendance_ip_validation_enabled',
            field=models.BooleanField(
                default=True,
                help_text=(
                    'Require employees to connect from a registered IP/network to clock in/out. '
                    'Disable only if your public IP changes frequently (e.g. dynamic router). '
                    'GPS and selfie requirements still apply when disabled.'
                ),
            ),
        ),
        migrations.AddField(
            model_name='company',
            name='require_attendance_gps_when_ip_disabled',
            field=models.BooleanField(
                default=True,
                help_text='When IP validation is disabled, require GPS from employees before clocking.',
            ),
        ),
        migrations.AddField(
            model_name='company',
            name='require_attendance_selfie_when_ip_disabled',
            field=models.BooleanField(
                default=True,
                help_text='When IP validation is disabled, require a selfie from employees before clocking.',
            ),
        ),
    ]
