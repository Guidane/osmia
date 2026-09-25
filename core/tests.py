from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from core.apps import check_module_dependencies
from core.modules import dependency_order
from inventory.models import Part, StockMove
from assemblies.models import Assembly
from tasks.models import Task
from users.models import User


class ModuleFrameworkTests(TestCase):
    def test_dependency_order(self):
        labels = [c.label for c in dependency_order()]
        self.assertLess(labels.index('users'), labels.index('tasks'))
        self.assertLess(labels.index('tasks'), labels.index('inventory'))
        self.assertLess(labels.index('inventory'), labels.index('assemblies'))

    def test_no_dependency_errors(self):
        self.assertEqual(check_module_dependencies(None), [])


class PageSmokeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('load_demo', stdout=StringIO())

    def setUp(self):
        self.client.login(username='admin', password='admin')

    def test_login_required(self):
        self.client.logout()
        resp = self.client.get(reverse('tasks:board'))
        self.assertRedirects(resp, reverse('users:login') + '?next=' + reverse('tasks:board'))

    def test_all_pages_render(self):
        user = User.objects.get(username='carla')
        task = Task.objects.get(title__startswith='Repair conveyor')
        part = Part.objects.get(part_number='BELT-C2')
        urls = [
            reverse('core:home'),
            reverse('users:list'), reverse('users:create'),
            reverse('users:detail', args=[user.pk]), reverse('users:edit', args=[user.pk]),
            reverse('tasks:board'), reverse('tasks:list'), reverse('tasks:gantt'),
            reverse('tasks:gantt') + '?weeks=12&start=2020-01-01&status=open&assignee=none',
            reverse('tasks:gantt') + '?weeks=abc&start=garbage', reverse('tasks:mine'), reverse('tasks:create'),
            reverse('tasks:detail', args=[task.pk]), reverse('tasks:edit', args=[task.pk]),
            reverse('tasks:delete', args=[task.pk]),
            reverse('inventory:part_list') + '?low=1&q=steel m8', reverse('inventory:part_create'),
            reverse('inventory:part_detail', args=[part.pk]),
            reverse('inventory:part_edit', args=[part.pk]),
            reverse('inventory:move_list'), reverse('inventory:move_create') + f'?task={task.pk}',
            reverse('inventory:category_list'), reverse('inventory:category_create'),
            reverse('inventory:category_edit', args=[part.category_id]),
            reverse('inventory:location_list'), reverse('inventory:location_create'),
            reverse('inventory:location_edit', args=[part.location_id]),
            reverse('assemblies:list'), reverse('assemblies:create'),
        ] + [reverse(name, args=[a.pk]) for a in Assembly.objects.all() for name in ('assemblies:detail', 'assemblies:edit')]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_home_shows_only_modules(self):
        resp = self.client.get(reverse('core:home'))
        for title in ('Users', 'Tasks', 'Inventory', 'Assemblies', 'Budgets', 'Devices', 'Harness'):
            self.assertContains(resp, f'<strong>{title}</strong>')
        self.assertNotContains(resp, 'class="widget')
        self.assertNotContains(resp, 'Depends on')
        self.assertNotContains(resp, 'Good to see you')

    def test_cross_module_panels(self):
        carla = User.objects.get(username='carla')
        resp = self.client.get(reverse('users:detail', args=[carla.pk]))
        self.assertContains(resp, 'Open tasks')          # from tasks
        self.assertContains(resp, 'Recent stock moves')  # from inventory
        task = Task.objects.get(title__startswith='Repair conveyor')
        resp = self.client.get(reverse('tasks:detail', args=[task.pk]))
        self.assertContains(resp, 'Materials')
        self.assertContains(resp, 'Conveyor belt 2m')

    def test_set_status(self):
        task = Task.objects.get(title__startswith='Repair conveyor')
        self.client.post(reverse('tasks:set_status', args=[task.pk]), {'status': 'done'})
        task.refresh_from_db()
        self.assertEqual(task.status, 'done')
        self.assertIsNotNone(task.completed_at)

    def test_gantt_bars(self):
        resp = self.client.get(reverse('tasks:gantt'))
        titles = [r['task'].title for r in resp.context['rows']]
        self.assertIn('Quarterly stock count', titles)
        self.assertIsNotNone(resp.context['today_left'])
        self.assertEqual(resp.context['window_start'].weekday(), 0)
        row = next(r for r in resp.context['rows'] if r['task'].title.startswith('Quarterly'))
        self.assertGreater(float(row['width']), 0)
        # A window far in the past contains nothing.
        resp = self.client.get(reverse('tasks:gantt') + '?start=2000-01-03')
        self.assertEqual(resp.context['rows'], [])

    def test_task_start_must_not_follow_due(self):
        resp = self.client.post(reverse('tasks:create'), {
            'title': 'Bad dates', 'status': 'todo', 'priority': 1,
            'start_date': '2026-10-10', 'due_date': '2026-10-01',
        })
        self.assertContains(resp, 'Due date cannot be before the start date.')

    def test_stock_moves_update_quantity(self):
        part = Part.objects.get(part_number='NUT-M8')
        url = reverse('inventory:move_create')
        self.client.post(url, {'part': part.pk, 'move_type': 'in', 'quantity': '50'})
        part.refresh_from_db()
        self.assertEqual(part.quantity_on_hand, 200)
        self.client.post(url, {'part': part.pk, 'move_type': 'adjust', 'quantity': '180'})
        part.refresh_from_db()
        self.assertEqual(part.quantity_on_hand, 180)
        self.assertEqual(part.moves.first().delta, -20)

    def test_cannot_issue_more_than_on_hand(self):
        part = Part.objects.get(part_number='BAT-FL48')
        resp = self.client.post(reverse('inventory:move_create'), {'part': part.pk, 'move_type': 'out', 'quantity': '5'})
        self.assertContains(resp, 'Only 1.00 pcs on hand')
        self.assertEqual(part.moves.count(), 1)

    def test_member_cannot_edit_other_users(self):
        self.client.login(username='bob', password='demo')
        alice = User.objects.get(username='alice')
        self.assertEqual(self.client.get(reverse('users:edit', args=[alice.pk])).status_code, 403)
        bob = User.objects.get(username='bob')
        self.assertEqual(self.client.get(reverse('users:edit', args=[bob.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('users:create')).status_code, 403)
