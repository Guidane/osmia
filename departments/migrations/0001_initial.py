import django.db.models.deletion
from django.db import migrations, models


def move_content_type(apps, schema_editor):
    """Department permissions (add/change/...) move with the model."""
    ContentType = apps.get_model('contenttypes', 'ContentType')
    if not ContentType.objects.filter(app_label='departments', model='department').exists():
        ContentType.objects.filter(app_label='users', model='department').update(app_label='departments')


def move_content_type_back(apps, schema_editor):
    ContentType = apps.get_model('contenttypes', 'ContentType')
    if not ContentType.objects.filter(app_label='users', model='department').exists():
        ContentType.objects.filter(app_label='departments', model='department').update(app_label='users')


class Migration(migrations.Migration):
    """Departments move out of the Users module into their own.

    The table (users_department) and every row in it stay exactly as they are;
    only Django's record of which app owns the model changes.
    """

    initial = True

    dependencies = [
        ('users', '0002_departments'),
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name='Department',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('name', models.CharField(max_length=100)),
                        ('parent', models.ForeignKey(
                            blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                            related_name='children', to='departments.department',
                        )),
                    ],
                    options={'ordering': ['name'], 'abstract': False, 'db_table': 'users_department'},
                ),
            ],
            database_operations=[],
        ),
        migrations.RunPython(move_content_type, move_content_type_back),
    ]
