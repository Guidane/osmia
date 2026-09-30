from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from assemblies.models import Assembly

from .models import Connector, Device, PinMap, Signal, TagOption


class DeviceTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('load_demo', stdout=StringIO())

    def setUp(self):
        self.client.login(username='admin', password='admin')
        self.pdu = Device.objects.get(part_number='PDU-100')


class DeviceTests(DeviceTestCase):
    def test_definition_uses_harness_format(self):
        d = self.pdu.definition()
        self.assertEqual([c['id'] for c in d['connectors']], ['J01', 'J02'])
        self.assertEqual(d['connectors'][0]['pins'][1],
                         {'id': '2', 'label': '13', 'signal': 'GND', 'tags': ['PWR_IN-', '', '', ''], 'set': None, 'set_type': ''})
        self.assertEqual(self.pdu.connectors.get(designator='J01').mating_designator, 'P01')

    def test_versions_only_on_change_and_can_be_restored(self):
        self.assertEqual(self.pdu.version, 1)
        self.assertFalse(self.pdu.snapshot())  # nothing changed
        j02 = self.pdu.connectors.get(designator='J02')
        j02.pins.filter(label='3').update(signal='SHIELD')
        self.assertTrue(self.pdu.snapshot())
        self.assertEqual(self.pdu.version, 2)
        self.pdu.activate_version(1)
        self.assertEqual(self.pdu.version, 1)
        self.assertEqual(self.pdu.connectors.get(designator='J02').pins.get(label='3').signal, 'GND')
        # The physical connector part survives restoring a version.
        self.assertEqual(self.pdu.connectors.get(designator='J01').part.part_number, 'DB25-F')

    def test_connector_editor_adds_renumbers_and_removes_pins(self):
        for name in ('RX', 'TX'):
            Signal.objects.get_or_create(name=name)
        url = reverse('devices:connector_create', args=[self.pdu.pk])
        resp = self.client.post(url, {
            'designator': 'j03', 'side': 'right', 'part': '', 'description': 'Aux',
            'pins-TOTAL_FORMS': 3, 'pins-INITIAL_FORMS': 0, 'pins-MIN_NUM_FORMS': 0, 'pins-MAX_NUM_FORMS': 1000,
            'pins-0-label': '1', 'pins-1-label': '2', 'pins-2-label': '3',
        })
        j03 = self.pdu.connectors.get(designator='J03')  # upper-cased
        self.assertRedirects(resp, self.pdu.get_absolute_url() + f'?connector={j03.pk}')
        self.assertEqual(list(j03.pins.values_list('label', flat=True)), ['1', '2', '3'])
        self.pdu.refresh_from_db()
        self.assertEqual(self.pdu.version, 2)

        pins = list(j03.pins.all())
        data = {
            'designator': 'J03', 'side': 'right', 'part': '', 'description': 'Aux',
            'pins-TOTAL_FORMS': 3, 'pins-INITIAL_FORMS': 3, 'pins-MIN_NUM_FORMS': 0, 'pins-MAX_NUM_FORMS': 1000,
        }
        for i, (pin, signal) in enumerate(zip(pins, ['RX', 'TX', 'GND'])):
            data.update({f'pins-{i}-id': pin.pk, f'pins-{i}-connector': j03.pk, f'pins-{i}-label': pin.label,
                         f'pins-{i}-signal': signal})
        data['pins-0-DELETE'] = 'on'
        self.client.post(reverse('devices:connector_edit', args=[self.pdu.pk, j03.pk]), data)
        self.assertEqual(list(j03.pins.values_list('position', 'signal')), [(1, 'TX'), (2, 'GND')])

    def test_add_pin_rows_one_at_a_time(self):
        j02 = self.pdu.connectors.get(designator='J02')
        url = reverse('devices:connector_edit', args=[self.pdu.pk, j02.pk])
        self.assertContains(self.client.get(url), 'id="btn-add-pin"')
        pins = list(j02.pins.all())
        data = {
            'designator': 'J02', 'side': j02.side, 'part': j02.part_id or '', 'description': j02.description,
            'pins-TOTAL_FORMS': len(pins) + 2, 'pins-INITIAL_FORMS': len(pins),
            'pins-MIN_NUM_FORMS': 0, 'pins-MAX_NUM_FORMS': 1000,
        }
        for i, pin in enumerate(pins):
            data.update({f'pins-{i}-id': pin.pk, f'pins-{i}-connector': j02.pk,
                         f'pins-{i}-label': pin.label, f'pins-{i}-signal': pin.signal})
        n = len(pins)
        Signal.objects.create(name='SHIELD')
        data.update({f'pins-{n}-label': '4', f'pins-{n}-signal': 'SHIELD',       # added with "+ Add pin"
                     f'pins-{n + 1}-label': '', f'pins-{n + 1}-signal': ''})    # blank new row: ignored
        self.client.post(url, data)
        self.assertEqual(list(j02.pins.values_list('position', 'label', 'signal'))[-1], (4, '4', 'SHIELD'))
        self.assertEqual(j02.pins.count(), 4)

    def test_duplicate_designator_rejected(self):
        resp = self.client.post(reverse('devices:connector_create', args=[self.pdu.pk]), {
            'designator': 'J01', 'side': 'left', 'part': '', 'description': '',
            'pins-TOTAL_FORMS': 0, 'pins-INITIAL_FORMS': 0, 'pins-MIN_NUM_FORMS': 0, 'pins-MAX_NUM_FORMS': 1000,
        })
        self.assertContains(resp, 'already has a J01')

    def test_external_device_has_no_assembly(self):
        assembly = Assembly.objects.create(name='Inverter', assembly_type=Assembly.Type.DEVICE)
        resp = self.client.post(reverse('devices:create'), {
            'name': 'Inverter', 'origin': 'external', 'role': 'other', 'assembly': assembly.pk, 'color': '#3b7dd8',
        })
        self.assertContains(resp, 'External devices are not built by us')

    def test_assembly_of_type_device_gets_connectors(self):
        assembly = Assembly.objects.create(name='Inverter 3kW', assembly_type=Assembly.Type.DEVICE)
        resp = self.client.get(assembly.get_absolute_url())
        self.assertContains(resp, 'Define connectors')
        resp = self.client.post(reverse('devices:from_assembly', args=[assembly.pk]))
        device = Device.objects.get(assembly=assembly)
        self.assertRedirects(resp, device.get_absolute_url())
        self.assertContains(self.client.get(self.pdu.assembly.get_absolute_url()), 'Power in')

    def test_part_page_shows_connector_use(self):
        resp = self.client.get(Connector.objects.get(device=self.pdu, designator='J01').part.get_absolute_url())
        self.assertContains(resp, 'Used as a connector on')

    def test_device_page_sidebar_and_views(self):
        j01 = self.pdu.connectors.get(designator='J01')
        page = self.client.get(self.pdu.get_absolute_url())
        # Sidebar: details link plus every connector.
        self.assertContains(page, 'Device details')
        self.assertContains(page, f'?connector={j01.pk}"')
        self.assertContains(page, f'?connector={self.pdu.connectors.get(designator="J02").pk}"')
        # By default the right side shows the details (owner, role, versions, harness projects).
        self.assertContains(page, 'Product (unit we build)')
        self.assertContains(page, 'Carla Rossi')
        self.assertContains(page, 'Harness projects')
        # Clicking a connector shows its pins instead.
        page = self.client.get(self.pdu.get_absolute_url() + f'?connector={j01.pk}')
        self.assertContains(page, 'Edit pins')
        self.assertContains(page, '<td>13</td><td>GND</td>')
        self.assertContains(page, '<td><code>PWR_IN-</code></td>')
        self.assertContains(page, 'DB25-F')
        self.assertNotContains(page, 'Versions</h2>')
        # Another device's connector id isn't shown here.
        other = Connector.objects.exclude(device=self.pdu).first()
        self.assertContains(self.client.get(self.pdu.get_absolute_url() + f'?connector={other.pk}'), 'Device details</h2>')

    def test_saving_pins_returns_to_that_connector(self):
        j02 = self.pdu.connectors.get(designator='J02')
        pins = list(j02.pins.all())
        data = {'designator': 'J02', 'side': j02.side, 'part': j02.part_id or '', 'description': j02.description,
                'pins-TOTAL_FORMS': len(pins), 'pins-INITIAL_FORMS': len(pins),
                'pins-MIN_NUM_FORMS': 0, 'pins-MAX_NUM_FORMS': 1000}
        for i, pin in enumerate(pins):
            data.update({f'pins-{i}-id': pin.pk, f'pins-{i}-connector': j02.pk, f'pins-{i}-label': pin.label, f'pins-{i}-signal': pin.signal})
        resp = self.client.post(reverse('devices:connector_edit', args=[self.pdu.pk, j02.pk]), data)
        self.assertRedirects(resp, self.pdu.get_absolute_url() + f'?connector={j02.pk}')

    def test_pages_render(self):
        for url in [
            reverse('devices:list'), reverse('devices:list') + '?origin=external&role=power_supply&q=psu',
            reverse('devices:create'), reverse('devices:create') + '?origin=external',
            self.pdu.get_absolute_url(), reverse('devices:edit', args=[self.pdu.pk]),
            reverse('devices:connector_create', args=[self.pdu.pk]),
            reverse('devices:connector_edit', args=[self.pdu.pk, self.pdu.connectors.first().pk]),
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)


def connector_post(connector, pins, **extra):
    """Form data for the connector editor: pins = [(pin or None, {field: value})]."""
    data = {'designator': connector.designator, 'side': connector.side, 'gender': connector.gender,
            'part': connector.part_id or '', 'details': connector.details, 'description': connector.description,
            'pins-TOTAL_FORMS': len(pins), 'pins-INITIAL_FORMS': sum(1 for p, _ in pins if p),
            'pins-MIN_NUM_FORMS': 0, 'pins-MAX_NUM_FORMS': 1000, **extra}
    for i, (pin, values) in enumerate(pins):
        if pin:
            data.update({f'pins-{i}-id': pin.pk, f'pins-{i}-connector': connector.pk})
            base = {'label': pin.label, 'signal': pin.signal, **pin.tag_fields(), 'set_number': pin.set_number or '', 'set_type': pin.set_type}
        else:
            base = {'label': '', 'signal': '', 'tag1': '', 'tag2': '', 'tag3': '', 'tag4': '', 'set_number': '', 'set_type': ''}
        for k, v in {**base, **values}.items():
            data[f'pins-{i}-{k}'] = v
    return data


class PinDetailsTests(DeviceTestCase):
    def test_four_tag_columns_with_their_own_lists(self):
        j02 = self.pdu.connectors.get(designator='J02')
        pins = list(j02.pins.all())
        url = reverse('devices:connector_edit', args=[self.pdu.pk, j02.pk])
        page = self.client.get(url)
        for column in range(1, 5):
            self.assertContains(page, f'name="pins-0-tag{column}"')
            self.assertContains(page, f'data-column="{column}"')
        self.assertContains(page, '+ Add new…')
        self.assertContains(page, '<option value="CAN1_H" selected>CAN1_H</option>')  # from the Tag 1 list
        # A value typed with "+ Add new…" is saved and joins its column's list; repeats are fine.
        resp = self.client.post(url, connector_post(j02, [
            (pins[0], {'tag2': 'Bus A', 'tag4': 'Front'}), (pins[1], {'tag2': 'Bus A'}), (pins[2], {'tag3': '__new__'}),
        ]))
        self.assertRedirects(resp, j02.get_absolute_url())
        self.assertEqual(list(j02.pins.values_list('tag2', flat=True)), ['Bus A', 'Bus A', ''])
        self.assertEqual(j02.pins.get(label='3').tag3, '')  # "+ Add new…" without a value is ignored
        self.assertEqual(TagOption.names()[2], ['Bus A'])
        self.assertEqual(TagOption.names()[4], ['Front'])
        self.assertIn('CAN1_H', TagOption.names()[1])
        self.assertEqual(self.pdu.definition()['connectors'][1]['pins'][0]['tags'], ['CAN1_H', 'Bus A', '', 'Front'])
        # Another connector's Tag 2 dropdown now offers it.
        j01 = self.pdu.connectors.get(designator='J01')
        self.assertContains(self.client.get(reverse('devices:connector_edit', args=[self.pdu.pk, j01.pk])), '<option value="Bus A">Bus A</option>')

    def test_tags_page_renames_and_blocks_deleting_used_ones(self):
        j01 = self.pdu.connectors.get(designator='J01')
        j01.pins.filter(label='1').update(tag3='Left')
        TagOption.objects.create(column=3, name='Left')
        TagOption.objects.create(column=3, name='Unused')
        options = list(TagOption.objects.all())
        data = {'tags-TOTAL_FORMS': len(options), 'tags-INITIAL_FORMS': len(options), 'tags-MIN_NUM_FORMS': 0, 'tags-MAX_NUM_FORMS': 1000}
        for i, o in enumerate(options):
            data.update({f'tags-{i}-id': o.pk, f'tags-{i}-column': o.column, f'tags-{i}-name': 'Port side' if o.name == 'Left' else o.name})
            if o.name in ('Unused', 'PWR_IN+'):
                data[f'tags-{i}-DELETE'] = 'on'
        resp = self.client.post(reverse('devices:tags'), data, follow=True)
        self.assertContains(resp, 'Still used, so not deleted: Tag 1: PWR_IN+')
        self.assertEqual(j01.pins.get(label='1').tag3, 'Port side')
        self.assertFalse(TagOption.objects.filter(name='Unused').exists())
        self.assertTrue(TagOption.objects.filter(name='PWR_IN+').exists())
        self.assertContains(self.client.get(reverse('devices:list')), reverse('devices:tags'))

    def test_sets_gender_details_and_signal_list(self):
        j02 = self.pdu.connectors.get(designator='J02')
        pins = list(j02.pins.all())
        data = connector_post(j02, [(pins[0], {'set_number': 3, 'set_type': 'twisted'}), (pins[1], {'signal': 'NOT_A_SIGNAL'}), (pins[2], {})],
                              gender='socket', details='M12 8-pin A-coded', part='')
        resp = self.client.post(reverse('devices:connector_edit', args=[self.pdu.pk, j02.pk]), data)
        self.assertContains(resp, 'Select a valid choice')  # signals come from the shared list
        data['pins-1-signal'] = 'GND'
        self.client.post(reverse('devices:connector_edit', args=[self.pdu.pk, j02.pk]), data)
        j02.refresh_from_db()
        self.assertEqual((j02.gender, j02.details, j02.part), ('socket', 'M12 8-pin A-coded', None))
        first = j02.pins.first()
        self.assertEqual((first.set_number, first.set_type), (3, 'twisted'))
        page = self.client.get(j02.get_absolute_url())
        self.assertContains(page, 'M12 8-pin A-coded')
        self.assertContains(page, '<td>3</td><td>Twisted</td>')
        self.assertNotContains(page, '<th class="num">#</th>')
        self.assertNotContains(self.client.get(reverse('devices:connector_edit', args=[self.pdu.pk, j02.pk])), 'add_pins')

    def test_every_pin_column_sorts_both_ways(self):
        j01 = self.pdu.connectors.get(designator='J01')
        j01.pins.filter(label='1').update(tag2='b', set_number=2)
        j01.pins.filter(label='13').update(tag2='a', set_number=10)
        base = j01.get_absolute_url()
        pins = lambda sort: [p.label for p in self.client.get(base + f'&sort={sort}').context['pins']]
        self.assertEqual(pins('tag1'), ['2', '14', '1', '13'])      # PWR_AUX+, PWR_AUX-, PWR_IN+, PWR_IN-
        self.assertEqual(pins('-tag1'), ['13', '1', '14', '2'])
        self.assertEqual(pins('tag2'), ['13', '1', '2', '14'])      # a, b, then the pins without one
        self.assertEqual(pins('-tag2'), ['1', '13', '2', '14'])     # still empty last
        self.assertEqual(pins('set'), ['1', '13', '2', '14'])       # 2 before 10
        self.assertEqual(pins('pin'), ['1', '2', '13', '14'])
        page = self.client.get(base + '&sort=tag2')
        for key in ('pin', 'signal', 'tag1', 'tag2', 'tag3', 'tag4', 'set', 'set_type'):
            self.assertContains(page, f'sort={key}"' if key != 'tag2' else 'sort=-tag2"')

    def test_signals_page_renames_everywhere_and_blocks_deleting_used_ones(self):
        from harness.models import SignalRule
        SignalRule.objects.create(signal_a='PWR', signal_b='PWR')
        signals = list(Signal.objects.all())
        data = {'signals-TOTAL_FORMS': len(signals) + 1, 'signals-INITIAL_FORMS': len(signals),
                'signals-MIN_NUM_FORMS': 0, 'signals-MAX_NUM_FORMS': 1000}
        for i, s in enumerate(signals):
            data.update({f'signals-{i}-id': s.pk, f'signals-{i}-name': 'VBUS' if s.name == 'PWR' else s.name, f'signals-{i}-description': ''})
            if s.name == 'GND':
                data[f'signals-{i}-DELETE'] = 'on'
        data[f'signals-{len(signals)}-name'] = 'SHIELD'
        resp = self.client.post(reverse('devices:signals'), data, follow=True)
        self.assertContains(resp, 'Still used, so not deleted: GND')
        self.assertTrue(Signal.objects.filter(name='VBUS').exists())
        self.assertTrue(Signal.objects.filter(name='SHIELD').exists())
        self.assertTrue(Signal.objects.filter(name='GND').exists())
        self.assertFalse(self.pdu.connectors.get(designator='J01').pins.filter(signal='PWR').exists())
        self.assertTrue(SignalRule.objects.filter(signal_a='VBUS', signal_b='VBUS').exists())
        self.assertFalse(SignalRule.objects.filter(signal_a='PWR').exists())
        self.assertContains(self.client.get(reverse('devices:list')), reverse('devices:signals'))

    def test_clone_connector(self):
        j02 = self.pdu.connectors.get(designator='J02')
        resp = self.client.post(reverse('devices:connector_clone', args=[self.pdu.pk, j02.pk]))
        copy = self.pdu.connectors.get(designator='J03')
        self.assertRedirects(resp, reverse('devices:connector_edit', args=[self.pdu.pk, copy.pk]))
        self.assertEqual(list(copy.pins.values_list('label', 'signal', 'tag1', 'tag2', 'set_number')),
                         list(j02.pins.values_list('label', 'signal', 'tag1', 'tag2', 'set_number')))
        self.assertEqual(copy.part, j02.part)
        self.pdu.refresh_from_db()
        self.assertEqual(self.pdu.version, 2)

    def test_pinout_images_on_the_connector(self):
        j01 = self.pdu.connectors.get(designator='J01')
        page = self.client.get(j01.get_absolute_url())
        self.assertContains(page, 'Pinout images')
        self.assertContains(page, reverse('core:image_upload', args=['devices.connector', j01.pk]))


class InterconnectTests(DeviceTestCase):
    def test_pin_mapping_and_versions(self):
        adapter = Device.objects.create(name='Adapter', role=Device.Role.INTERCONNECT)
        a = Connector.objects.create(device=adapter, designator='J01', side='left')
        b = Connector.objects.create(device=adapter, designator='J02', side='right')
        for c in (a, b):
            for i in (1, 2):
                c.pins.create(position=i, label=str(i))
        adapter.snapshot()
        url = reverse('devices:pin_mapping', args=[adapter.pk])
        self.client.post(url, {'by_position': '1', 'from_connector': a.pk, 'to_connector': b.pk})
        self.assertEqual(adapter.pin_maps.count(), 2)
        self.assertEqual(adapter.definition()['pin_map'], [['J01', '1', 'J02', '1'], ['J01', '2', 'J02', '2']])
        # Cross over: J01.1 -> J02.2, J01.2 -> J02.1
        pa, pb = list(a.pins.all()), list(b.pins.all())
        self.client.post(url, {'from': [pa[0].pk, pa[1].pk], 'to': [pb[1].pk, pb[0].pk]})
        adapter.refresh_from_db()
        self.assertEqual(adapter.definition()['pin_map'], [['J01', '1', 'J02', '2'], ['J01', '2', 'J02', '1']])
        adapter.activate_version(adapter.version - 1)  # restoring a version restores its mapping
        self.assertEqual(adapter.definition()['pin_map'], [['J01', '1', 'J02', '1'], ['J01', '2', 'J02', '2']])
        self.assertContains(self.client.get(adapter.get_absolute_url()), 'Pin mapping')
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_extension_copies_the_pinout(self):
        j02 = self.pdu.connectors.get(designator='J02')
        j02.gender = 'socket'
        j02.save()
        ext = Device.make_extension(self.pdu, j02)
        self.assertTrue(ext.is_interconnect)
        inp, out = ext.connectors.get(designator='J01'), ext.connectors.get(designator='J02')
        self.assertEqual((inp.gender, out.gender, out.part), ('pin', 'socket', j02.part))
        self.assertEqual(list(out.pins.values_list('label', 'signal', 'tag1')), list(j02.pins.values_list('label', 'signal', 'tag1')))
        self.assertEqual(ext.pin_maps.count(), j02.pins.count())
        self.assertEqual(ext.version, 1)
