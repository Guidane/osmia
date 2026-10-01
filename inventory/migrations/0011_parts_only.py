from django.db import migrations, models


class Migration(migrations.Migration):
    """Parts only describe things now: stock, locations, cost and reorder level
    moved to the Stock module (stock 0001 copied them first). Parts get links to
    the parts they mate with or accept, and the tools to work with them."""

    dependencies = [
        ('inventory', '0010_stock_transfers'),
        ('stock', '0001_initial'),
        ('tools', '0001_initial'),
    ]

    operations = [
        migrations.RemoveField(model_name='part', name='location'),
        migrations.RemoveField(model_name='part', name='cost'),
        migrations.RemoveField(model_name='part', name='reorder_level'),
        migrations.RemoveField(model_name='part', name='quantity_on_hand'),
        # The tables stay; Stock owns these models now.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(name='StockMove'),
                migrations.DeleteModel(name='Location'),
            ],
            database_operations=[],
        ),
        migrations.AddField(
            model_name='part',
            name='mates_with',
            field=models.ManyToManyField(blank=True, help_text='Parts this one connects to, both ways: e.g. a 9-pin plug mates with a 9-socket receptacle.', to='inventory.part'),
        ),
        migrations.AddField(
            model_name='part',
            name='fits',
            field=models.ManyToManyField(blank=True, help_text='Parts used in or with this one: e.g. a D-sub housing accepts its crimp contacts.', related_name='fits_into', to='inventory.part', verbose_name='accepts'),
        ),
        migrations.AddField(
            model_name='part',
            name='tools',
            field=models.ManyToManyField(blank=True, help_text='Tools to work with it, e.g. the crimp tool for a contact.', related_name='parts', to='tools.tool'),
        ),
    ]
