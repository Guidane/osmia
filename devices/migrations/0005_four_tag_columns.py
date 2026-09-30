from django.db import migrations, models


def options_from_pins(apps, schema_editor):
    """Each tag column's list starts with the values the pins already use."""
    Pin = apps.get_model('devices', 'Pin')
    TagOption = apps.get_model('devices', 'TagOption')
    for column in range(1, 5):
        names = set(Pin.objects.exclude(**{f'tag{column}': ''}).values_list(f'tag{column}', flat=True))
        TagOption.objects.bulk_create([TagOption(column=column, name=n) for n in sorted(names)])


class Migration(migrations.Migration):

    dependencies = [
        ('devices', '0004_tags_signals_sets_interconnects'),
    ]

    operations = [
        # Tags may now repeat within a connector: they're picked from lists.
        migrations.RemoveConstraint(model_name='pin', name='unique_pin_tag_per_connector'),
        migrations.RenameField(model_name='pin', old_name='tag', new_name='tag1'),
        migrations.AlterField(model_name='pin', name='tag1', field=models.CharField(blank=True, max_length=50, verbose_name='Tag 1')),
        migrations.AddField(model_name='pin', name='tag2', field=models.CharField(blank=True, max_length=50, verbose_name='Tag 2')),
        migrations.AddField(model_name='pin', name='tag3', field=models.CharField(blank=True, max_length=50, verbose_name='Tag 3')),
        migrations.AddField(model_name='pin', name='tag4', field=models.CharField(blank=True, max_length=50, verbose_name='Tag 4')),
        migrations.CreateModel(
            name='TagOption',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('column', models.PositiveSmallIntegerField(choices=[(1, 'Tag 1'), (2, 'Tag 2'), (3, 'Tag 3'), (4, 'Tag 4')])),
                ('name', models.CharField(max_length=50)),
            ],
            options={'ordering': ['column', 'name']},
        ),
        migrations.AddConstraint(
            model_name='tagoption',
            constraint=models.UniqueConstraint(fields=('column', 'name'), name='unique_tag_option'),
        ),
        migrations.RunPython(options_from_pins, migrations.RunPython.noop),
    ]
