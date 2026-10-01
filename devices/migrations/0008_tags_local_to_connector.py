import django.db.models.deletion
from django.db import migrations, models


def lists_per_connector(apps, schema_editor):
    """The shared lists become each connector's own: a connector offers the tags its pins use."""
    TagOption = apps.get_model('devices', 'TagOption')
    Pin = apps.get_model('devices', 'Pin')
    TagOption.objects.all().delete()
    seen = set()
    rows = []
    for pin in Pin.objects.all():
        for column in range(1, 5):
            value = getattr(pin, f'tag{column}')
            key = (pin.connector_id, column, value)
            if value and key not in seen:
                seen.add(key)
                rows.append(TagOption(connector_id=pin.connector_id, column=column, name=value))
    TagOption.objects.bulk_create(rows)


class Migration(migrations.Migration):

    dependencies = [
        ('devices', '0007_connector_function_no_gender'),
    ]

    operations = [
        migrations.RemoveConstraint(model_name='tagoption', name='unique_tag_option'),
        migrations.AddField(
            model_name='tagoption',
            name='connector',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='tag_options', to='devices.connector'),
        ),
        migrations.RunPython(lists_per_connector, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='tagoption',
            name='connector',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='tag_options', to='devices.connector'),
        ),
        migrations.AddConstraint(
            model_name='tagoption',
            constraint=models.UniqueConstraint(fields=('connector', 'column', 'name'), name='unique_tag_option_per_connector'),
        ),
    ]
