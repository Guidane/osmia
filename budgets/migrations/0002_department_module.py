import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Budget.department points at the Departments module; nothing changes in the database."""

    dependencies = [
        ('budgets', '0001_initial'),
        ('departments', '0001_initial'),
    ]
    # Must be repointed before the Users module drops its copy of the model.
    run_before = [
        ('users', '0003_department_module'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name='budget',
                    name='department',
                    field=models.ForeignKey(
                        blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                        related_name='budgets', to='departments.department',
                    ),
                ),
            ],
            database_operations=[],
        ),
    ]
