import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Department now lives in the Departments module; nothing changes in the database."""

    dependencies = [
        ('users', '0002_departments'),
        ('departments', '0001_initial'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name='user',
                    name='department',
                    field=models.ForeignKey(
                        blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                        related_name='users', to='departments.department',
                    ),
                ),
                migrations.DeleteModel(name='Department'),
            ],
            database_operations=[],
        ),
    ]
