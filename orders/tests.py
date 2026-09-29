from decimal import Decimal
from io import StringIO

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from budgets.models import Budget, Spending
from inventory.models import Part

from .models import Order


class OrderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('load_demo', stdout=StringIO())
        # These tests are about orders alone, not the demo automation rules.
        from automations.models import Rule
        Rule.objects.update(active=False)

    def setUp(self):
        self.client.login(username='admin', password='admin')
        self.order = Order.objects.get(supplier='Connector Supply Co.')

    def test_numbering_and_total(self):
        self.assertTrue(self.order.number.startswith('PO-'))
        self.assertEqual(self.order.total, Decimal('20') * Decimal('2.60') + Decimal('10') * Decimal('2.40'))

    def test_receiving_books_stock_once_and_counts_against_budget(self):
        part = Part.objects.get(part_number='DB25-F')
        before = part.quantity_on_hand
        budget = self.order.budget
        self.assertEqual(Spending().own[budget.pk], 0)
        self.order.set_status(Order.Status.PLACED)
        self.assertEqual(Spending().own[budget.pk], self.order.total)
        self.order.set_status(Order.Status.RECEIVED)
        self.order.set_status(Order.Status.RECEIVED)  # no-op
        part.refresh_from_db()
        self.assertEqual(part.quantity_on_hand, before + 20)
        self.assertEqual(part.moves.filter(note__contains=self.order.number).count(), 1)
        with self.assertRaises(ValidationError):
            self.order.set_status(Order.Status.DRAFT)

    def test_empty_order_cannot_be_placed(self):
        empty = Order.objects.create(supplier='Nobody')
        with self.assertRaises(ValidationError):
            empty.set_status(Order.Status.PLACED)

    def test_pages(self):
        for url in (reverse('orders:list'), self.order.get_absolute_url(), reverse('orders:edit', args=[self.order.pk]),
                    reverse('orders:create'), self.order.budget.get_absolute_url()):
            self.assertEqual(self.client.get(url).status_code, 200, url)
        self.assertContains(self.client.get(self.order.budget.get_absolute_url()), self.order.number)

    def test_create_with_lines_and_place_from_the_page(self):
        part = Part.objects.get(part_number='DB25-M')
        response = self.client.post(reverse('orders:create'), {
            'supplier': 'Acme', 'budget': Budget.objects.first().pk, 'notes': '',
            'lines-TOTAL_FORMS': '1', 'lines-INITIAL_FORMS': '0', 'lines-MIN_NUM_FORMS': '0', 'lines-MAX_NUM_FORMS': '1000',
            'lines-0-part': part.pk, 'lines-0-quantity': '4', 'lines-0-unit_price': '1.50',
        })
        order = Order.objects.get(supplier='Acme')
        self.assertRedirects(response, order.get_absolute_url())
        self.assertEqual(order.total, Decimal('6.00'))
        self.client.post(reverse('orders:set_status', args=[order.pk]), {'status': 'placed'})
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PLACED)
        # Placed orders can no longer be edited.
        self.assertRedirects(self.client.get(reverse('orders:edit', args=[order.pk])), order.get_absolute_url())
