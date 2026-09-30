import json
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from . import lookup
from .models import Attribute, Category, Part

# A trimmed Mouser "search/partnumber" response in the documented format.
MOUSER_RESPONSE = {
    'Errors': [],
    'SearchResults': {
        'NumberOfResult': 2,
        'Parts': [
            {'MouserPartNumber': '571-OTHER', 'ManufacturerPartNumber': 'OTHER-1', 'Description': 'Not this one'},
            {
                'MouserPartNumber': '571-5747461-3',
                'ManufacturerPartNumber': '5747461-3',
                'Manufacturer': 'TE Connectivity',
                'Description': 'D-Sub Standard Connectors 25P RCPT',
                'Category': 'D-Sub Standard Connectors',
                'DataSheetUrl': 'https://example.com/5747461.pdf',
                'ProductDetailUrl': 'https://www.mouser.com/ProductDetail/571-5747461-3',
                'ROHSStatus': 'RoHS Compliant',
                'LifecycleStatus': '',
                'ProductAttributes': [
                    {'AttributeName': 'Number of Positions', 'AttributeValue': '25 Position'},
                    {'AttributeName': 'Gender', 'AttributeValue': 'Receptacle (Female)'},
                    {'AttributeName': 'Packaging', 'AttributeValue': 'Tray'},
                    {'AttributeName': 'Packaging', 'AttributeValue': 'Bulk'},
                ],
                'PriceBreaks': [
                    {'Quantity': 10, 'Price': '$2.10', 'Currency': 'USD'},
                    {'Quantity': 1, 'Price': '$2.45', 'Currency': 'USD'},
                ],
            },
        ],
    },
}


class FakeResponse:
    def __init__(self, data):
        self.body = json.dumps(data).encode()

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class LookupParsingTests(TestCase):
    def test_parse_mouser_picks_exact_part(self):
        info = lookup.parse_mouser('5747461-3', MOUSER_RESPONSE)
        self.assertEqual(info.manufacturer, 'TE Connectivity')
        self.assertFalse(hasattr(info, 'unit_price'))  # prices are never looked up
        self.assertEqual(info.attributes['Number of Positions'], '25 Position')
        self.assertEqual(info.attributes['Packaging'], 'Tray, Bulk')
        self.assertEqual(info.attributes['Manufacturer'], 'TE Connectivity')
        self.assertEqual(info.attributes['Datasheet'], 'https://example.com/5747461.pdf')
        self.assertNotIn('Lifecycle', info.attributes)  # empty values are skipped

    def test_parse_mouser_errors_and_empty(self):
        with self.assertRaises(lookup.LookupFailed):
            lookup.parse_mouser('x', {'Errors': [{'Message': 'Invalid unique identifier.'}]})
        self.assertIsNone(lookup.parse_mouser('x', {'Errors': [], 'SearchResults': {'Parts': []}}))

    @override_settings(OSMIA_MOUSER_API_KEY='')
    def test_not_configured(self):
        with self.assertRaises(lookup.LookupNotConfigured):
            lookup.lookup('5747461-3')

    @override_settings(OSMIA_MOUSER_API_KEY='test-key')
    def test_request_sent_to_mouser(self):
        with mock.patch('urllib.request.urlopen', return_value=FakeResponse(MOUSER_RESPONSE)) as urlopen:
            info = lookup.lookup('5747461-3')
        request = urlopen.call_args.args[0]
        self.assertTrue(request.full_url.startswith(lookup.MOUSER_URL + '?apiKey=test-key'))
        self.assertEqual(json.loads(request.data)['SearchByPartRequest'],
                         {'mouserPartNumber': '5747461-3', 'partSearchOptions': 'Exact'})
        self.assertEqual(info.source, 'Mouser')


class LookupViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('load_demo', stdout=StringIO())

    def setUp(self):
        self.client.login(username='admin', password='admin')

    @override_settings(OSMIA_MOUSER_API_KEY='test-key')
    def test_lookup_endpoint(self):
        url = reverse('inventory:part_lookup')
        with mock.patch('urllib.request.urlopen', return_value=FakeResponse(MOUSER_RESPONSE)):
            data = self.client.get(url, {'part_number': '5747461-3'}).json()
        self.assertEqual(data['part']['description'], 'D-Sub Standard Connectors 25P RCPT')
        self.assertEqual(self.client.get(url).status_code, 400)
        with mock.patch('urllib.request.urlopen', return_value=FakeResponse({'Errors': [], 'SearchResults': {'Parts': []}})):
            self.assertEqual(self.client.get(url, {'part_number': 'nope'}).status_code, 404)

    @override_settings(OSMIA_MOUSER_API_KEY='')
    def test_lookup_endpoint_explains_missing_key(self):
        resp = self.client.get(reverse('inventory:part_lookup'), {'part_number': 'X'})
        self.assertEqual(resp.status_code, 503)
        self.assertIn('OSMIA_MOUSER_API_KEY', resp.json()['error'])

    def test_add_missing_attributes_then_save(self):
        connectors = Category.objects.get(name='Connectors')
        existing = connectors.attributes.get(name='pins')
        resp = self.client.post(
            reverse('inventory:category_add_attributes', args=[connectors.pk]),
            json.dumps({'names': ['Number of Positions', 'PINS', 'Number of Positions', '']}), content_type='application/json',
        )
        attrs = {a['name']: a['id'] for a in resp.json()['attributes']}
        self.assertEqual(attrs['pins'], existing.pk)  # matched case-insensitively, not duplicated
        positions = Attribute.objects.get(category=connectors, name='Number of Positions')
        self.assertEqual(attrs['Number of Positions'], positions.pk)

        # The part form now accepts a value for the new attribute.
        socket = Part.objects.get(part_number='DB25-F')
        self.client.post(reverse('inventory:part_edit', args=[socket.pk]), {
            'part_number': socket.part_number, 'name': socket.name, 'category': connectors.pk, 'unit': 'pcs',
            'cost': '2.60', 'reorder_level': '10',
            'is_active': 'on', f'attr_{positions.pk}': '25 Position',
        })
        self.assertEqual(socket.attribute_values.get(attribute=positions).value, '25 Position')

    def test_part_form_has_lookup(self):
        resp = self.client.get(reverse('inventory:part_create'))
        self.assertContains(resp, 'id="btn-lookup"')
        self.assertContains(resp, 'data-attr-name="thread"')


class LocationCodeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('load_demo', stdout=StringIO())

    def setUp(self):
        self.client.login(username='admin', password='admin')

    def test_labels(self):
        from .locations import labels
        self.assertEqual(labels('A', 3), ['A', 'B', 'C'])
        self.assertEqual(labels('a', 2, 'y'), ['y', 'z'])
        self.assertEqual(labels('A', 3, 'Z'), ['Z', 'AA', 'AB'])
        self.assertEqual(labels('1', 3, '5'), ['5', '6', '7'])
        self.assertEqual(labels('01', 3), ['01', '02', '03'])
        self.assertEqual(labels('01', 2, '99'), ['099', '100'])

    def test_code_joins_labels_and_follows_changes(self):
        from .models import Location
        hall = Location.objects.create(name='Hall', label='H')
        row = Location.objects.create(name='Rack row A', label='A', parent=hall)
        shelf = Location.objects.create(name='Shelf 1', label='1', parent=row)
        self.assertEqual(shelf.code, 'HA1')
        self.assertEqual(str(shelf), 'Hall > Rack row A > Shelf 1 (HA1)')
        hall.label, hall.name = 'W', 'Warehouse 2'
        hall.save()
        shelf.refresh_from_db()
        self.assertEqual((shelf.code, shelf.path), ('WA1', 'Warehouse 2 > Rack row A > Shelf 1'))

    def test_generate_rows_racks_shelves(self):
        from .models import Location
        hall = Location.objects.create(name='Hall')
        data = {'parent': hall.pk}
        for i, (name, count, style) in enumerate([('Rack row', 4, 'A'), ('Rack', 6, '1'), ('Shelf', 4, 'A')]):
            data.update({f'level-{i}-name': name, f'level-{i}-count': count, f'level-{i}-style': style, f'level-{i}-start': ''})
        response = self.client.post(reverse('inventory:location_generate'), data)
        self.assertRedirects(response, hall.get_absolute_url())
        under = Location.objects.filter(pk__in=hall.descendant_ids())
        self.assertEqual(under.count(), 4 + 24 + 96)
        shelf = Location.objects.get(code='A1A')
        self.assertEqual(shelf.name, 'Shelf A')
        self.assertEqual(shelf.path, 'Hall > Rack row A > Rack 1 > Shelf A')
        self.assertTrue(Location.objects.filter(code='D6D').exists())
        self.assertEqual(sorted(Location.objects.get(code='B3').children.values_list('code', flat=True)), ['B3A', 'B3B', 'B3C', 'B3D'])

        # Again with one more rack per row: only the new ones are added.
        data['level-1-count'] = 7
        self.client.post(reverse('inventory:location_generate'), data)
        self.assertEqual(Location.objects.filter(pk__in=hall.descendant_ids()).count(), 4 + 28 + 112)

        # Parts can be found by their location's code.
        part = Part.objects.first()
        part.location = shelf
        part.save()
        self.assertContains(self.client.get(reverse('inventory:part_list') + '?q=a1a'), part.part_number)
        for url in (reverse('inventory:location_list'), shelf.get_absolute_url(), part.get_absolute_url()):
            self.assertContains(self.client.get(url), 'A1A')

    def test_bad_input_and_limits(self):
        from .models import Location
        before = Location.objects.count()
        url = reverse('inventory:location_generate')
        for data in (
            {'level-0-name': 'Rack', 'level-0-count': 'x', 'level-0-style': '1'},
            {'level-0-name': '', 'level-0-count': '3', 'level-0-style': '1'},
            {'level-0-name': 'Rack', 'level-0-count': '3', 'level-0-style': 'A', 'level-0-start': '7'},
            {'level-0-name': 'Row', 'level-0-count': '100', 'level-0-style': 'A',
             'level-1-name': 'Rack', 'level-1-count': '100', 'level-1-style': '1'},
            {},
        ):
            with self.subTest(data=data):
                self.assertEqual(self.client.post(url, data).status_code, 200)
        self.assertEqual(Location.objects.count(), before)
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_sibling_labels_are_unique(self):
        from .models import Location
        row = Location.objects.create(name='Row', label='R')
        Location.objects.create(name='Rack 1', label='1', parent=row)
        response = self.client.post(reverse('inventory:location_create'), {'name': 'Other', 'label': '1', 'parent': row.pk})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already has the label')


class LocationDeleteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('load_demo', stdout=StringIO())

    def setUp(self):
        from .locations import generate, clean_levels
        from .models import Location
        self.client.login(username='admin', password='admin')
        self.hall = Location.objects.create(name='Hall', label='H')
        generate(self.hall, clean_levels([{'name': 'Row', 'count': 2, 'style': 'A'}, {'name': 'Shelf', 'count': 3, 'style': '1'}]))
        self.shelf = Location.objects.get(code='HB2')

    def test_refused_while_parts_are_kept_there_or_below(self):
        from .models import Location
        part = Part.objects.first()
        part.location = self.shelf
        part.save()
        for loc in (self.hall, self.shelf.parent, self.shelf):
            url = reverse('inventory:location_delete', args=[loc.pk])
            page = self.client.get(url)
            self.assertContains(page, "can't be deleted")
            self.assertContains(page, part.part_number)
            self.client.post(url)
        self.assertEqual(Location.objects.filter(pk__in={self.hall.pk, *self.hall.descendant_ids()}).count(), 1 + 2 + 6)

    def test_empty_location_is_deleted_with_its_sub_locations(self):
        from .models import Location
        empty_row = Location.objects.get(code='HA')
        response = self.client.post(reverse('inventory:location_delete', args=[empty_row.pk]))
        self.assertRedirects(response, self.hall.get_absolute_url())
        self.assertFalse(Location.objects.filter(code__startswith='HA').exists())
        self.assertTrue(Location.objects.filter(code='HB1').exists())
        page = self.client.get(reverse('inventory:location_delete', args=[self.hall.pk]))
        self.assertContains(page, '4 sub-locations')
        self.client.post(reverse('inventory:location_delete', args=[self.hall.pk]))
        self.assertFalse(Location.objects.filter(code__startswith='H').exists())


class LocationTableTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('load_demo', stdout=StringIO())

    def test_quantities_roll_up_and_rows_delete_back_to_the_table(self):
        from .locations import clean_levels, generate
        from .models import Location
        self.client.login(username='admin', password='admin')
        hall = Location.objects.create(name='Hall', label='H')
        generate(hall, clean_levels([{'name': 'Row', 'count': 2, 'style': 'A'}, {'name': 'Shelf', 'count': 2, 'style': '1'}]))
        a, b = list(Part.objects.all()[:2])
        Part.objects.filter(pk=a.pk).update(location=Location.objects.get(code='HA1'), quantity_on_hand=5)
        Part.objects.filter(pk=b.pk).update(location=Location.objects.get(code='HA2'), quantity_on_hand=2.5)
        url = reverse('inventory:location_list')
        rows = {n.code: n for n in self.client.get(url).context['object_list'] if n.code.startswith('H')}
        self.assertEqual((rows['H'].part_count, rows['H'].quantity, rows['H'].sub_count), (2, 7.5, 6))
        self.assertEqual((rows['HA'].part_count, rows['HA'].quantity), (2, 7.5))
        self.assertEqual((rows['HB'].part_count, rows['HB'].quantity, rows['HB'].sub_count), (0, 0, 2))
        page = self.client.get(url)
        self.assertContains(page, reverse('inventory:location_delete', args=[rows['HB'].pk]))
        self.assertNotContains(page, 'action="' + reverse('inventory:location_delete', args=[rows['HA'].pk]))
        response = self.client.post(reverse('inventory:location_delete', args=[rows['HB'].pk]), {'next': url})
        self.assertRedirects(response, url)
        self.assertFalse(Location.objects.filter(code__startswith='HB').exists())


class TransferTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('load_demo', stdout=StringIO())

    def setUp(self):
        from .locations import clean_levels, generate
        from .models import Location
        self.client.login(username='admin', password='admin')
        hall = Location.objects.create(name='Hall', label='H')
        generate(hall, clean_levels([{'name': 'Shelf', 'count': 3, 'style': 'A'}]))
        self.a, self.b = Location.objects.get(code='HA'), Location.objects.get(code='HB')
        self.p1, self.p2 = list(Part.objects.all()[:2])

    def test_move_selected_parts_from_the_stock_moves_page(self):
        from .models import StockMove
        before = {p.pk: p.quantity_on_hand for p in (self.p1, self.p2)}
        url = reverse('inventory:move_list')
        page = self.client.get(url)
        self.assertContains(page, 'id="transfer-form"')
        self.assertContains(page, 'class="row-select" name="parts"')
        # The same part picked twice (two rows of its moves) moves once.
        response = self.client.post(reverse('inventory:transfer'), {
            'parts': [self.p1.pk, self.p2.pk, self.p1.pk], 'location': self.b.pk, 'next': url, 'note': 'Reorganised'})
        self.assertRedirects(response, url)
        for p in (self.p1, self.p2):
            p.refresh_from_db()
            self.assertEqual(p.location, self.b)
            self.assertEqual(p.quantity_on_hand, before[p.pk])
        moves = StockMove.objects.filter(move_type=StockMove.Type.TRANSFER)
        self.assertEqual(moves.count(), 2)
        self.assertEqual({m.to_location for m in moves}, {self.b})
        self.assertEqual(moves.filter(part=self.p1).get().note, 'Reorganised')
        self.assertContains(self.client.get(url), '<code>HB</code>')
        # Already there: nothing new is logged.
        self.client.post(reverse('inventory:transfer'), {'parts': [self.p1.pk], 'location': self.b.pk})
        self.assertEqual(moves.count(), 2)
        # From a location's page and a part's page.
        self.assertContains(self.client.get(self.b.get_absolute_url()), 'id="transfer-form"')
        self.client.post(reverse('inventory:transfer'), {'parts': [self.p1.pk], 'location': self.a.pk, 'next': self.p1.get_absolute_url()})
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.location, self.a)
        page = self.client.get(self.p1.get_absolute_url())
        self.assertContains(page, 'Transfer')
        self.assertContains(page, '<code>HB</code>')

    def test_needs_a_location_and_rows(self):
        from .models import StockMove
        self.client.post(reverse('inventory:transfer'), {'parts': [self.p1.pk]})
        self.client.post(reverse('inventory:transfer'), {'location': self.a.pk})
        self.assertFalse(StockMove.objects.filter(move_type=StockMove.Type.TRANSFER).exists())
        self.assertNotContains(self.client.get(reverse('inventory:move_create')), 'value="transfer"')
