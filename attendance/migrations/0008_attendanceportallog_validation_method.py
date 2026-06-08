from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('attendance', '0007_attendancerecord_night_differential_minutes'),
    ]

    operations = [
        migrations.AddField(
            model_name='attendanceportallog',
            name='validation_method',
            field=models.CharField(
                max_length=30,
                blank=True,
                choices=[
                    ('IP',                     'IP Match'),
                    ('GPS_SELFIE',             'GPS + Selfie'),
                    ('IP_DISABLED_GPS_SELFIE', 'IP Disabled — GPS/Selfie'),
                    ('BLOCKED',                'Blocked'),
                ],
                help_text='Which validation path was used for this portal interaction.',
            ),
        ),
    ]
