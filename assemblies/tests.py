from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from inventory.models import Category, Part
from tasks.models import Task

from .models import Assembly, TaskLink


def bom_post(assembly, lines, **fields):
    """POST data for the assembly form: header fields plus component rows."""
    data = {
        'name': assembly.name, 'assembly_type': assembly.assembly_type, 'status': assembly.status,
        'version': assembly.version, 'build_instructions': '', 'usage_instructions': '',
        'components-TOTAL_FORMS': len(lines), 'components-INITIAL_FORMS': 0,
        'components-MIN_NUM_FORMS': 0, 'components-MAX_NUM_FORMS': 1000,
    }
    data.update(fields)
    for i, (ref, qty) in enumerate(lines):
        data[f'components-{i}-component'] = ref
        data[f'components-{i}-quantity'] = qty
    return data


class AssemblyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('load_demo', stdout=StringIO())

    def setUp(self):
        self.client.login(username='admin', password='admin')
        self.conveyor = Assembly.objects.get(name='Conveyor section')
        self.roller = Assembly.objects.get(name='Idler roller')
        self.parts = {p.part_number: p for p in Part.objects.all()}

    def current_lines(self, assembly):
        return [(c.ref, str(c.quantity)) for c in assembly.components.all()]

    def test_structure_multiplies_through_sub_assemblies(self):
        totals = {r['part'].part_number: r['needed'] for r in self.conveyor.total_parts()}
        self.assertEqual(totals['608ZZ'], Decimal(12))   # 6 rollers x 2 bearings
        self.assertEqual(totals['BLT-M8'], Decimal(18))  # 6 x 1 in rollers + 12 on the frame
        self.assertEqual(totals['DB25-F'], Decimal(1))
        # 40 bearings cover 3 builds, but one of the 3 belts went to the repair task: 2 builds.
        self.assertEqual(self.conveyor.buildable_count(), 2)

    def test_unchanged_edit_keeps_bom(self):
        # Submit the edit page exactly as rendered (INITIAL_FORMS included).
        url = reverse('assemblies:edit', args=[self.conveyor.pk])
        page = self.client.get(url)
        formset = page.context['formset']
        data = bom_post(self.conveyor, self.current_lines(self.conveyor))
        data['components-INITIAL_FORMS'] = formset.initial_form_count()
        self.client.post(url, data)
        self.conveyor.refresh_from_db()
        self.assertEqual(self.conveyor.components.count(), 5)
        self.assertEqual(self.conveyor.revision, 1)

    def test_revision_bumps_only_on_bom_or_version_change(self):
        url = reverse('assemblies:edit', args=[self.roller.pk])
        lines = self.current_lines(self.roller)
        self.client.post(url, bom_post(self.roller, lines, name='Idler roller (renamed)'))
        self.roller.refresh_from_db()
        self.assertEqual((self.roller.name, self.roller.revision), ('Idler roller (renamed)', 1))

        self.client.post(url, bom_post(self.roller, lines + [('p:%d' % self.parts['GLV-L'].pk, '1')]))
        self.roller.refresh_from_db()
        self.assertEqual(self.roller.revision, 2)

        self.client.post(url, bom_post(self.roller, self.current_lines(self.roller), version='3'))
        self.roller.refresh_from_db()
        self.assertEqual((self.roller.version, self.roller.revision), ('3', 3))

    def test_cannot_create_cycle(self):
        # The conveyor contains the roller, so the roller can't contain the conveyor.
        url = reverse('assemblies:edit', args=[self.roller.pk])
        resp = self.client.get(url)
        self.assertNotContains(resp, f'value="a:{self.conveyor.pk}"')
        resp = self.client.post(url, bom_post(self.roller, [(f'a:{self.conveyor.pk}', '1')]))
        self.assertEqual(resp.status_code, 200)  # re-rendered with an error, not saved
        self.assertFalse(self.roller.components.filter(child_assembly=self.conveyor).exists())
        resp = self.client.post(url, bom_post(self.roller, [(f'a:{self.roller.pk}', '1')]))
        self.assertFalse(self.roller.components.filter(child_assembly=self.roller).exists())

    def test_duplicate_rows_rejected(self):
        ref = f'p:{self.parts["NUT-M8"].pk}'
        resp = self.client.post(reverse('assemblies:create'), bom_post(Assembly(name='Dup'), [(ref, '1'), (ref, '2')]))
        self.assertContains(resp, 'Listed twice')
        self.assertFalse(Assembly.objects.filter(name='Dup').exists())

    def test_create_assembly_with_sub_assembly(self):
        resp = self.client.post(reverse('assemblies:create'), bom_post(
            Assembly(name='Twin roller'), [(f'a:{self.roller.pk}', '2'), (f'p:{self.parts["BLT-M8"].pk}', '4')],
        ))
        twin = Assembly.objects.get(name='Twin roller')
        self.assertRedirects(resp, twin.get_absolute_url())
        self.assertEqual(twin.revision, 1)
        self.assertEqual(twin.components.count(), 2)

    def test_build_task_and_task_panel(self):
        resp = self.client.post(reverse('assemblies:create_build_task', args=[self.roller.pk]))
        task = Task.objects.get(assembly_link__assembly=self.roller)
        self.assertRedirects(resp, reverse('tasks:edit', args=[task.pk]))
        resp = self.client.get(task.get_absolute_url())
        self.assertContains(resp, 'Idler roller v1')
        # Unlink from the task page.
        self.client.post(reverse('assemblies:link_task', args=[task.pk]), {'assembly': ''})
        self.assertFalse(TaskLink.objects.filter(task=task).exists())

    def test_part_page_lists_assemblies(self):
        resp = self.client.get(self.parts['608ZZ'].get_absolute_url())
        self.assertContains(resp, 'Used in assemblies')
        self.assertContains(resp, 'Idler roller')

    def test_part_in_bom_cannot_be_deleted(self):
        from django.db.models import ProtectedError
        with self.assertRaises(ProtectedError):
            self.parts['608ZZ'].delete()


class PartTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('load_demo', stdout=StringIO())

    def setUp(self):
        self.client.login(username='admin', password='admin')

    def test_part_has_no_interconnect_fields(self):
        plug = Part.objects.get(part_number='DB25-M')
        for url in (plug.get_absolute_url(), reverse('inventory:part_edit', args=[plug.pk]), reverse('inventory:part_list')):
            resp = self.client.get(url)
            self.assertNotContains(resp, 'nterconnect')
            self.assertNotContains(resp, 'Mates with')

    def test_attribute_values_follow_category(self):
        bolt = Part.objects.get(part_number='BLT-M8')
        fasteners = bolt.category
        thread = fasteners.attributes.get(name='thread')
        data = {
            'part_number': bolt.part_number, 'name': bolt.name, 'category': fasteners.pk, 'unit': 'pcs',
            'cost': '0.12', 'reorder_level': '200',
            'is_active': 'on', f'attr_{thread.pk}': 'M10',
        }
        self.client.post(reverse('inventory:part_edit', args=[bolt.pk]), data)
        self.assertEqual(bolt.attribute_values.get(attribute=thread).value, 'M10')
        self.assertFalse(bolt.attribute_values.filter(attribute__name='material').exists())  # cleared

        # Moving to a category without those attributes drops the old values.
        data['category'] = Category.objects.get(name='Safety').pk
        self.client.post(reverse('inventory:part_edit', args=[bolt.pk]), data)
        self.assertEqual(bolt.attribute_values.count(), 0)

    def test_category_cannot_be_its_own_ancestor(self):
        hardware = Category.objects.get(name='Hardware')
        fasteners = Category.objects.get(name='Fasteners')
        self.assertEqual(fasteners.full_path(), 'Hardware > Fasteners')
        resp = self.client.post(reverse('inventory:category_edit', args=[hardware.pk]), {
            'name': 'Hardware', 'parent': fasteners.pk,
            'attrs-TOTAL_FORMS': 0, 'attrs-INITIAL_FORMS': 0, 'attrs-MIN_NUM_FORMS': 0, 'attrs-MAX_NUM_FORMS': 1000,
        })
        self.assertContains(resp, 'Select a valid choice')
        hardware.refresh_from_db()
        self.assertIsNone(hardware.parent)

    def test_search_by_attribute_value(self):
        resp = self.client.get(reverse('inventory:part_list') + '?q=SKF')
        self.assertEqual([p.part_number for p in resp.context['object_list']], ['608ZZ'])
