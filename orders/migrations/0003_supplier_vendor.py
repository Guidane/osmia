"""Order.supplier was free text; it is now a link to a Vendor.

Each distinct supplier name becomes a vendor (or joins one with the same name,
ignoring case), so every order keeps its supplier.
"""
import django.db.models.deletion
from django.db import migrations, models


def text_to_vendor(apps, schema_editor):
    Order = apps.get_model('orders', 'Order')
    Vendor = apps.get_model('vendors', 'Vendor')
    for order in Order.objects.exclude(supplier=''):
        name = order.supplier.strip()
        vendor = Vendor.objects.filter(name__iexact=name).first() or Vendor.objects.create(name=name)
        order.vendor = vendor
        order.save(update_fields=['vendor'])


def vendor_to_text(apps, schema_editor):
    Order = apps.get_model('orders', 'Order')
    for order in Order.objects.exclude(vendor=None).select_related('vendor'):
        order.supplier = order.vendor.name
        order.save(update_fields=['supplier'])


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0002_orderline_location_orderline_received_at_and_more'),
        ('vendors', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='vendor',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name='orders', to='vendors.vendor'),
        ),
        migrations.RunPython(text_to_vendor, vendor_to_text),
        migrations.RemoveField(model_name='order', name='supplier'),
        migrations.RenameField(model_name='order', old_name='vendor', new_name='supplier'),
    ]
