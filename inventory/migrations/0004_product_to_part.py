from django.db import migrations


class Migration(migrations.Migration):
    """Product becomes Part (as in Waggle V3). Renames keep existing rows and stock history."""

    dependencies = [
        ('inventory', '0003_initial'),
    ]

    operations = [
        migrations.RenameModel('Product', 'Part'),
        migrations.RenameField('Part', 'sku', 'part_number'),
        migrations.RenameField('StockMove', 'product', 'part'),
    ]
