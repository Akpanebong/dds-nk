from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
from django.utils import timezone


def migrate_staff_users(apps, schema_editor):
    StaffProfile = apps.get_model('core', 'StaffProfile')
    Group = apps.get_model('auth', 'Group')
    db_alias = schema_editor.connection.alias
    cursor = schema_editor.connection.cursor()
    mapping = {}

    # Fresh databases use StaffProfile as the user model and therefore do not
    # have the legacy auth_user table. Keep this migration compatible with
    # both fresh installs and databases being upgraded from the old model.
    table_names = schema_editor.connection.introspection.table_names()
    if 'auth_user' in table_names:
        cursor.execute(
            'SELECT id, username, email, first_name, last_name, password, is_active, '
            'is_staff, is_superuser, last_login, date_joined FROM auth_user'
        )
        legacy_users = {
            row[0]: {
                'username': row[1], 'email': row[2], 'first_name': row[3],
                'last_name': row[4], 'password': row[5], 'is_active': row[6],
                'is_staff': row[7], 'is_superuser': row[8], 'last_login': row[9],
                'date_joined': row[10],
            }
            for row in cursor.fetchall()
        }
    else:
        legacy_users = {}
    for profile in StaffProfile.objects.using(db_alias).all():
        old_user = legacy_users[profile.user_id]
        profile.username = old_user['username'] or f'staff-{profile.pk:06d}'
        profile.email = old_user['email']
        profile.first_name = old_user['first_name']
        profile.last_name = old_user['last_name']
        profile.password = old_user['password']
        profile.is_active = old_user['is_active']
        profile.is_staff = old_user['is_staff']
        profile.is_superuser = old_user['is_superuser']
        profile.last_login = old_user['last_login']
        profile.date_joined = old_user['date_joined']
        profile.staff_reg_no = f'DDS-{timezone.localdate().year % 100:02d}-{profile.pk:06d}'
        profile.phone_num = profile.phone or None
        profile.save(using=db_alias, update_fields=[
            'username', 'email', 'first_name', 'last_name', 'password',
            'is_active', 'is_staff', 'is_superuser', 'last_login',
            'date_joined', 'staff_reg_no', 'phone_num',
        ])
        mapping[profile.user_id] = profile.pk

    tables = [
        ('core_auditlog', 'actor_id'),
        ('hr_staffrecord', 'user_id'),
        ('meal_datacollection', 'submitted_by_id'),
        ('meal_report', 'created_by_id'),
        ('procurement_procurementrequest', 'requested_by_id'),
        ('django_admin_log', 'user_id'),
    ]
    for table, column in tables:
        for old_id, new_id in mapping.items():
            cursor.execute(
                f'UPDATE {table} SET {column} = %s WHERE {column} = %s',
                [new_id, old_id],
            )
    if mapping:
        for old_id, new_id in mapping.items():
            cursor.execute(
                'INSERT OR IGNORE INTO core_staffprofile_groups (staffprofile_id, group_id) '
                'SELECT %s, group_id FROM auth_user_groups WHERE user_id = %s',
                [new_id, old_id],
            )
    groups = {
        'meal': Group.objects.using(db_alias).get_or_create(name='MEAL')[0],
        'procurement': Group.objects.using(db_alias).get_or_create(name='Procurement')[0],
        'hr': Group.objects.using(db_alias).get_or_create(name='HR')[0],
    }
    for profile in StaffProfile.objects.using(db_alias).all():
        for access_name, group in groups.items():
            if profile.is_superuser or getattr(profile, f'{access_name}_access'):
                cursor.execute(
                    'INSERT OR IGNORE INTO core_staffprofile_groups (staffprofile_id, group_id) VALUES (%s, %s)',
                    [profile.pk, group.pk],
                )


class Migration(migrations.Migration):
    dependencies = [
        ('auth', '0012_alter_user_first_name_max_length'),
        ('core', '0003_add_slugs'),
    ]
    operations = [
        migrations.AddField(model_name='staffprofile', name='username', field=models.CharField(blank=True, max_length=150, null=True, unique=True)),
        migrations.AddField(model_name='staffprofile', name='email', field=models.EmailField(max_length=254, null=True, unique=True)),
        migrations.AddField(model_name='staffprofile', name='first_name', field=models.CharField(blank=True, max_length=150)),
        migrations.AddField(model_name='staffprofile', name='last_name', field=models.CharField(blank=True, max_length=150)),
        migrations.AddField(model_name='staffprofile', name='staff_reg_no', field=models.CharField(blank=True, max_length=30, null=True, unique=True)),
        migrations.AddField(model_name='staffprofile', name='phone_num', field=models.CharField(blank=True, max_length=40, null=True, unique=True)),
        migrations.AddField(model_name='staffprofile', name='password', field=models.CharField(default='', max_length=128)),
        migrations.AddField(model_name='staffprofile', name='last_login', field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name='staffprofile', name='date_joined', field=models.DateTimeField(default=timezone.now)),
        migrations.AddField(model_name='staffprofile', name='is_active', field=models.BooleanField(default=True)),
        migrations.AddField(model_name='staffprofile', name='is_staff', field=models.BooleanField(default=False)),
        migrations.AddField(model_name='staffprofile', name='is_superuser', field=models.BooleanField(default=False)),
        migrations.AddField(model_name='staffprofile', name='groups', field=models.ManyToManyField(blank=True, related_name='staffprofile_set', related_query_name='staffprofile', to='auth.group')),
        migrations.AddField(model_name='staffprofile', name='user_permissions', field=models.ManyToManyField(blank=True, related_name='staffprofile_set', related_query_name='staffprofile', to='auth.permission')),
        migrations.RunPython(migrate_staff_users, migrations.RunPython.noop),
        migrations.RemoveField(model_name='staffprofile', name='user'),
        migrations.RemoveField(model_name='staffprofile', name='phone'),
        migrations.AlterField(model_name='staffprofile', name='username', field=models.CharField(max_length=150, unique=True)),
        migrations.AlterField(model_name='staffprofile', name='email', field=models.EmailField(max_length=254, unique=True)),
        migrations.AlterField(model_name='staffprofile', name='staff_reg_no', field=models.CharField(max_length=30, unique=True)),
        migrations.AlterField(model_name='staffprofile', name='meal_access', field=models.BooleanField(default=False)),
        migrations.AlterField(model_name='staffprofile', name='procurement_access', field=models.BooleanField(default=False)),
        migrations.AlterField(model_name='staffprofile', name='hr_access', field=models.BooleanField(default=False)),
        migrations.AlterField(model_name='auditlog', name='actor', field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
    ]
