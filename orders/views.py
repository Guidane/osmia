from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.views.generic import DetailView, ListView

from core import hooks

from .forms import OrderForm, OrderLineFormSet
from .models import Order


class OrderListView(LoginRequiredMixin, ListView):
    model = Order

    def get_queryset(self):
        qs = Order.objects.select_related('budget').prefetch_related('lines')
        if self.request.GET.get('status') in Order.Status.values:
            qs = qs.filter(status=self.request.GET['status'])
        return qs

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs, statuses=Order.Status.choices)


class OrderDetailView(LoginRequiredMixin, DetailView):
    model = Order

    def get_context_data(self, **kwargs):
        o = self.object
        budget = o.budget
        if budget:
            from budgets.models import Spending
            Spending().annotate([budget])
        return super().get_context_data(
            **kwargs,
            lines=o.lines.select_related('part'),
            budget=budget,
            can_place=o.can_become(Order.Status.PLACED),
            can_receive=o.can_become(Order.Status.RECEIVED),
            can_cancel=o.can_become(Order.Status.CANCELLED),
            panels=hooks.collect('order_detail_panels', self.request, o),
        )


@login_required
def order_form(request, pk=None):
    order = get_object_or_404(Order, pk=pk) if pk else Order()
    if order.pk and order.status != Order.Status.DRAFT:
        messages.error(request, 'Only draft orders can be edited.')
        return redirect(order)
    form = OrderForm(request.POST or None, instance=order)
    formset = OrderLineFormSet(request.POST or None, instance=order, prefix='lines')
    if request.method == 'POST' and form.is_valid() and formset.is_valid():
        with transaction.atomic():
            if not order.pk:
                form.instance.created_by = request.user
            order = form.save()
            formset.instance = order
            formset.save()
        messages.success(request, f'{order.number} saved.')
        return redirect(order)
    return render(request, 'orders/order_form.html', {
        'form': form, 'formset': formset, 'order': order,
        'heading': f'Edit {order.number}' if order.pk else 'New order',
    })


@login_required
@require_POST
def set_status(request, pk):
    order = get_object_or_404(Order, pk=pk)
    try:
        order.set_status(request.POST.get('status', ''), user=request.user)
        messages.success(request, f'{order.number} is now {order.get_status_display().lower()}.')
    except (ValidationError, ValueError) as exc:
        messages.error(request, ' '.join(getattr(exc, 'messages', [str(exc)])))
    return redirect(order)
