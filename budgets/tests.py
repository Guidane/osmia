from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from inventory.models import Part, StockMove
from tasks.models import Task
from users.models import Department, User

from .models import Budget, Spending, TaskBudget


class DemoDataTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('load_demo', stdout=StringIO())

    def setUp(self):
        self.client.login(username='admin', password='admin')
        self.budgets = {b.budget_number: b for b in Budget.objects.all()}
        self.repair = Task.objects.get(title__startswith='Repair conveyor')


class BudgetTests(DemoDataTestCase):
    def test_spend_rolls_up_the_tree(self):
        # The demo repair task (Field Service) was issued one 89.00 conveyor belt.
        spending = Spending()
        fs, ops, fy = self.budgets['B-OPS-FS'], self.budgets['B-OPS'], self.budgets['B-2026']
        self.assertEqual(TaskBudget.objects.get(task=self.repair).budget, fs)
        self.assertEqual(spending.own[fs.pk], Decimal('89.00'))
        self.assertEqual(spending.total[ops.pk], Decimal('89.00'))
        self.assertEqual(spending.total[fy.pk], Decimal('89.00'))
        self.assertEqual(spending.own[ops.pk], 0)
        self.assertEqual(spending.total[self.budgets['B-ENG'].pk], 0)

    def test_cost_is_fixed_when_moved_and_returns_reduce_it(self):
        belt = Part.objects.get(part_number='BELT-C2')
        belt.cost = Decimal('500.00')
        belt.save()
        self.assertEqual(Spending().own[self.budgets['B-OPS-FS'].pk], Decimal('89.00'))
        StockMove.record(belt, StockMove.Type.IN, 1, task=self.repair, note='Returned')  # at 500.00
        self.assertEqual(Spending().own[self.budgets['B-OPS-FS'].pk], Decimal('-411.00'))

    def test_budget_must_match_task_department(self):
        url = reverse('budgets:link_task', args=[self.repair.pk])
        self.client.post(url, {'budget': self.budgets['B-ENG'].pk})
        self.assertEqual(TaskBudget.objects.get(task=self.repair).budget, self.budgets['B-OPS-FS'])
        self.client.post(url, {'budget': ''})
        self.assertFalse(TaskBudget.objects.filter(task=self.repair).exists())

    def test_task_page_shows_budget_panel(self):
        resp = self.client.get(self.repair.get_absolute_url())
        self.assertContains(resp, 'B-OPS-FS')
        self.assertContains(resp, 'This task has cost 89.00')

    def test_over_budget_flagged(self):
        fs = self.budgets['B-OPS-FS']
        fs.amount = Decimal('50')
        fs.save()
        resp = self.client.get(fs.get_absolute_url())
        self.assertContains(resp, 'Over budget')

    def test_pages_render(self):
        fs = self.budgets['B-OPS-FS']
        dept = Department.objects.get(name='Warehouse')
        for url in [
            reverse('budgets:list'), reverse('budgets:list') + f'?department={dept.pk}',
            reverse('budgets:create'), reverse('budgets:create') + f'?parent={fs.pk}',
            fs.get_absolute_url(), reverse('budgets:edit', args=[fs.pk]),
            self.budgets['B-2026'].get_absolute_url(),
            reverse('users:department_list'), reverse('users:department_create'),
            dept.get_absolute_url(), reverse('users:department_edit', args=[dept.pk]),
            reverse('users:list') + f'?department={dept.parent_id}',
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_members_cannot_manage_budgets(self):
        self.client.login(username='bob', password='demo')
        self.assertEqual(self.client.get(reverse('budgets:create')).status_code, 403)
        self.assertEqual(self.client.get(reverse('budgets:list')).status_code, 200)


class DepartmentTests(DemoDataTestCase):
    def test_tree_and_members(self):
        ops = Department.objects.get(name='Operations', parent=None)
        self.assertEqual(Department.objects.get(name='Warehouse').full_path(), 'Operations > Warehouse')
        self.assertEqual(
            sorted(ops.members(include_sub=True).values_list('username', flat=True)), ['alice', 'bob', 'carla'],
        )
        resp = self.client.get(reverse('users:list') + f'?department={ops.pk}')
        self.assertEqual(len(resp.context['object_list']), 3)

    def test_task_department_defaults_to_assignee(self):
        bob = User.objects.get(username='bob')
        self.client.post(reverse('tasks:create'), {'title': 'Count bins', 'status': 'todo', 'priority': 1, 'assignee': bob.pk})
        self.assertEqual(Task.objects.get(title='Count bins').department, bob.department)

    def test_members_cannot_change_own_department(self):
        self.client.login(username='bob', password='demo')
        bob = User.objects.get(username='bob')
        marketing = Department.objects.get(name='Marketing')
        self.client.post(reverse('users:edit', args=[bob.pk]), {
            'first_name': 'Bob', 'last_name': 'Nguyen', 'email': 'bob@example.com',
            'job_title': 'Warehouse Lead', 'phone': '', 'department': marketing.pk,
        })
        bob.refresh_from_db()
        self.assertEqual(bob.department.name, 'Warehouse')

    def test_department_panel_lists_budgets(self):
        resp = self.client.get(Department.objects.get(name='Field Service').get_absolute_url())
        self.assertContains(resp, 'B-OPS-FS')
        self.assertContains(resp, 'Carla')
