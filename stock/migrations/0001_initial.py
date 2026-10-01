import django.db.models.deletion
from decimal import Decimal

from django.conf import settings
from django.db import migrations, models


def move_content_types(apps, schema_editor):
    """Locations and stock moves now belong to Stock: their images and log entries come along."""
    ContentType = apps.get_model('contenttypes', 'ContentType')
    for model in ('location', 'stockmove'):
        if not ContentType.objects.filter(app_label='stock', model=model).exists():
            ContentType.objects.filter(app_label='inventory', model=model).update(app_label='stock')


def move_content_types_back(apps, schema_editor):
    ContentType = apps.get_model('contenttypes', 'ContentType')
    for model in ('location', 'stockmove'):
        if not ContentType.objects.filter(app_label='inventory', model=model).exists():
            ContentType.objects.filter(app_label='stock', model=model).update(app_label='inventory')


def stock_from_parts(apps, schema_editor):
    """Each part's quantity on hand becomes stock at its location, its cost the
    average cost and its reorder level stays as it was."""
    Part = apps.get_model('inventory', 'Part')
    PartStock = apps.get_model('stock', 'PartStock')
    StockItem = apps.get_model('stock', 'StockItem')
    for part in Part.objects.all():
        PartStock.objects.create(part_id=part.pk, reorder_level=part.reorder_level or 0, average_cost=part.cost or 0)
        if part.quantity_on_hand or part.location_id:
            StockItem.objects.create(part_id=part.pk, location_id=part.location_id, quantity=part.quantity_on_hand or Decimal(0))


def rename_automation_keys(apps, schema_editor):
    """Rules that used the stock trigger/action under their old Inventory names."""
    if 'automations_rule' not in schema_editor.connection.introspection.table_names():
        return  # Automations isn't set up (yet): nothing to rename
    try:
        Rule = apps.get_model('automations', 'Rule')
    except LookupError:
        return
    for rule in Rule.objects.all():
        changed = False
        if rule.trigger == 'inventory.stock_low':
            rule.trigger, changed = 'stock.stock_low', True
        for step in rule.actions or []:
            if step.get('action') == 'inventory.stock_move':
                step['action'], changed = 'stock.stock_move', True
        if changed:
            rule.save()


class Migration(migrations.Migration):
    """Stock moves out of Inventory into its own module.

    The location and stock move tables stay exactly as they are (only Django's
    record of which app owns them changes); stock per location and each part's
    stock settings are new tables, filled from the parts.
    """

    initial = True

    dependencies = [
        ('inventory', '0010_stock_transfers'),
        ('tasks', '0006_task_batches'),
        ('contenttypes', '0002_remove_content_type_name'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name='Location',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('name', models.CharField(max_length=100)),
                        ('label', models.CharField(blank=True, help_text="Short code, e.g. A or 1. A location's code joins the labels down the tree: rack row A, rack 1, shelf A is A1A.", max_length=20)),
                        ('code', models.CharField(blank=True, db_index=True, editable=False, max_length=200)),
                        ('path', models.CharField(blank=True, editable=False, max_length=500)),
                        ('parent', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='children', to='stock.location')),
                    ],
                    options={'ordering': ['name'], 'abstract': False, 'db_table': 'inventory_location'},
                ),
                migrations.AddConstraint(
                    model_name='location',
                    constraint=models.UniqueConstraint(condition=models.Q(('label', ''), _negated=True), fields=('parent', 'label'), name='unique_location_label_per_parent'),
                ),
                migrations.CreateModel(
                    name='StockMove',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('move_type', models.CharField(choices=[('in', 'Receipt'), ('out', 'Issue'), ('adjust', 'Adjustment'), ('transfer', 'Transfer')], max_length=10, verbose_name='Type')),
                        ('delta', models.DecimalField(decimal_places=2, help_text='Signed change to quantity on hand.', max_digits=12)),
                        ('unit_cost', models.DecimalField(decimal_places=2, default=0, editable=False, max_digits=12)),
                        ('note', models.CharField(blank=True, max_length=255)),
                        ('created_at', models.DateTimeField(auto_now_add=True)),
                        ('from_location', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='stock.location')),
                        ('to_location', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='stock.location')),
                        ('part', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='moves', to='inventory.part')),
                        ('task', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='stock_moves', to='tasks.task')),
                        ('user', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='stock_moves', to=settings.AUTH_USER_MODEL)),
                    ],
                    options={'ordering': ['-created_at', '-id'], 'db_table': 'inventory_stockmove'},
                ),
            ],
            database_operations=[],
        ),
        migrations.RunPython(move_content_types, move_content_types_back),
        # New: where a receipt, issue or count happened (old moves: unknown).
        migrations.AddField(
            model_name='stockmove',
            name='location',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='moves', to='stock.location'),
        ),
        migrations.CreateModel(
            name='PartStock',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('reorder_level', models.DecimalField(decimal_places=2, default=0, help_text='Flag as low stock at or below this quantity (all locations together).', max_digits=12)),
                ('average_cost', models.DecimalField(decimal_places=4, default=0, help_text='Average cost of what has been received, per unit.', max_digits=12)),
                ('part', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='stock', to='inventory.part')),
            ],
            options={'verbose_name': 'part stock settings', 'verbose_name_plural': 'part stock settings'},
        ),
        migrations.CreateModel(
            name='StockItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('quantity', models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ('location', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='items', to='stock.location')),
                ('part', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='stock_items', to='inventory.part')),
            ],
            options={'ordering': ['part__part_number', 'location__path']},
        ),
        migrations.AddConstraint(
            model_name='stockitem',
            constraint=models.UniqueConstraint(fields=('part', 'location'), name='unique_stock_item'),
        ),
        migrations.RunPython(stock_from_parts, migrations.RunPython.noop),
        migrations.RunPython(rename_automation_keys, migrations.RunPython.noop),
    ]
