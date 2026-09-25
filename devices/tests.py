from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from assemblies.models import Assembly

from .models import Connector, Device


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
        self.assertEqual(d['connectors'][0]['pins'][1], {'id': '2', 'label': '13', 'signal': 'GND'})
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
        url = reverse('devices:connector_create', args=[self.pdu.pk])
        resp = self.client.post(url, {
            'designator': 'j03', 'side': 'right', 'part': '', 'description': 'Aux', 'add_pins': 3,
            'pins-TOTAL_FORMS': 0, 'pins-INITIAL_FORMS': 0, 'pins-MIN_NUM_FORMS': 0, 'pins-MAX_NUM_FORMS': 1000,
        })
        self.assertRedirects(resp, self.pdu.get_absolute_url())
        j03 = self.pdu.connectors.get(designator='J03')  # upper-cased
        self.assertEqual(list(j03.pins.values_list('label', flat=True)), ['1', '2', '3'])
        self.pdu.refresh_from_db()
        self.assertEqual(self.pdu.version, 2)

        pins = list(j03.pins.all())
        data = {
            'designator': 'J03', 'side': 'right', 'part': '', 'description': 'Aux', 'add_pins': '',
            'pins-TOTAL_FORMS': 3, 'pins-INITIAL_FORMS': 3, 'pins-MIN_NUM_FORMS': 0, 'pins-MAX_NUM_FORMS': 1000,
        }
        for i, (pin, signal) in enumerate(zip(pins, ['RX', 'TX', 'GND'])):
            data.update({f'pins-{i}-id': pin.pk, f'pins-{i}-connector': j03.pk, f'pins-{i}-label': pin.label,
                         f'pins-{i}-signal': signal})
        data['pins-0-DELETE'] = 'on'
        self.client.post(reverse('devices:connector_edit', args=[self.pdu.pk, j03.pk]), data)
        self.assertEqual(list(j03.pins.values_list('position', 'signal')), [(1, 'TX'), (2, 'GND')])

    def test_duplicate_designator_rejected(self):
        resp = self.client.post(reverse('devices:connector_create', args=[self.pdu.pk]), {
            'designator': 'J01', 'side': 'left', 'part': '', 'description': '', 'add_pins': 1,
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
