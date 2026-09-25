import django.db.models.deletion
from django.db import migrations, models


def text_to_departments(apps, schema_editor):
    """Turn each distinct free-text department into a Department record."""
    User = apps.get_model('users', 'User')
    Department = apps.get_model('users', 'Department')
    for user in User.objects.exclude(department_text=''):
        name = user.department_text.strip()
        if name:
            user.department, _ = Department.objects.get_or_create(name=name, parent=None)
            user.save(update_fields=['department'])


def departments_to_text(apps, schema_editor):
    User = apps.get_model('users', 'User')
    for user in User.objects.exclude(department=None).select_related('department'):
        user.department_text = user.department.name
        user.save(update_fields=['department_text'])


class Migration(migrations.Migration):
    dependencies = [
        ('users', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='Department',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('parent', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                    related_name='children', to='users.department',
                )),
            ],
            options={'ordering': ['name'], 'abstract': False},
        ),
        migrations.RenameField('User', 'department', 'department_text'),
        migrations.AddField(
            model_name='user',
            name='department',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name='users', to='users.department',
            ),
        ),
        migrations.RunPython(text_to_departments, departments_to_text),
        migrations.RemoveField('User', 'department_text'),
    ]
