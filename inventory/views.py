import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import Count, F, Q
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DetailView, FormView, ListView, UpdateView

from core import hooks
from core.trees import sorted_by_path

from . import lookup
from .forms import AttributeFormSet, CategoryForm, LocationForm, PartForm, StockMoveForm
from .models import Attribute, Category, Location, Part, StockMove


class PartListView(LoginRequiredMixin, ListView):
    model = Part
    paginate_by = 50

    def get_queryset(self):
        qs = Part.objects.select_related('category__parent', 'location__parent')
        g = self.request.GET
        for word in g.get('q', '').split():
            qs = qs.filter(
                Q(part_number__icontains=word) | Q(name__icontains=word)
                | Q(category__name__icontains=word) | Q(location__name__icontains=word)
                | Q(attribute_values__value__icontains=word)
            )
        if g.get('category'):
            category = Category.objects.filter(pk=g['category']).first()
            if category:
                qs = qs.filter(category_id__in={category.pk, *category.descendant_ids()})
        if g.get('location'):
            location = Location.objects.filter(pk=g['location']).first()
            if location:
                qs = qs.filter(location_id__in={location.pk, *location.descendant_ids()})
        if g.get('low'):
            qs = qs.filter(quantity_on_hand__lte=F('reorder_level'))
        if not g.get('archived'):
            qs = qs.filter(is_active=True)
        return qs.distinct()

    def get_context_data(self, **kwargs):
        return super().get_context_data(
            **kwargs,
            categories=Category.objects.select_related('parent'),
            locations=Location.objects.select_related('parent'),
        )


class PartDetailView(LoginRequiredMixin, DetailView):
    model = Part

    def get_context_data(self, **kwargs):
        return super().get_context_data(
            **kwargs,
            moves=self.object.moves.select_related('user', 'task')[:50],
            attribute_values=self.object.attribute_values.select_related('attribute'),
            panels=hooks.collect('part_detail_panels', self.request, self.object),
        )


class PartFormMixin(LoginRequiredMixin):
    model = Part
    form_class = PartForm
    template_name = 'inventory/part_form.html'

    def form_valid(self, form):
        with transaction.atomic():
            response = super().form_valid(form)
        messages.success(self.request, 'Part saved.')
        return response


class PartCreateView(PartFormMixin, CreateView):
    extra_context = {'heading': 'New part'}

    def get_initial(self):
        return {k: self.request.GET[k] for k in ('category', 'location') if self.request.GET.get(k)}


class PartUpdateView(PartFormMixin, UpdateView):
    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs, heading=f'Edit {self.object}', cancel_url=self.object.get_absolute_url())


@login_required
def part_lookup(request):
    """JSON: what an online provider knows about ?part_number=..."""
    part_number = request.GET.get('part_number', '').strip()
    if not part_number:
        return JsonResponse({'error': 'Enter a part number first.'}, status=400)
    try:
        info = lookup.lookup(part_number)
    except lookup.LookupNotConfigured as exc:
        return JsonResponse({'error': str(exc), 'not_configured': True}, status=503)
    except lookup.LookupFailed as exc:
        return JsonResponse({'error': str(exc)}, status=502)
    if info is None:
        return JsonResponse({'error': f'No part found for "{part_number}".'}, status=404)
    return JsonResponse({'part': info.as_dict()})


@login_required
@require_POST
def category_add_attributes(request, pk):
    """JSON in: {"names": [...]}; adds the missing ones to the category and
    returns every requested attribute as {name, id} (existing ones too)."""
    category = get_object_or_404(Category, pk=pk)
    try:
        names = json.loads(request.body or b'{}').get('names') or []
    except (ValueError, AttributeError):
        return HttpResponseBadRequest('Expected {"names": [...]}.')
    result = []
    for name in dict.fromkeys(str(n).strip()[:100] for n in names):
        if not name:
            continue
        attribute = (Attribute.objects.filter(category=category, name__iexact=name).first()
                     or Attribute.objects.create(category=category, name=name))
        result.append({'name': attribute.name, 'id': attribute.pk})
    return JsonResponse({'attributes': result})


class MoveListView(LoginRequiredMixin, ListView):
    model = StockMove
    paginate_by = 100

    def get_queryset(self):
        qs = StockMove.objects.select_related('part', 'task', 'user')
        if self.request.GET.get('type') in StockMove.Type.values:
            qs = qs.filter(move_type=self.request.GET['type'])
        return qs

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs, types=StockMove.Type.choices)


class MoveCreateView(LoginRequiredMixin, FormView):
    form_class = StockMoveForm
    template_name = 'core/form.html'
    extra_context = {'heading': 'New stock move'}

    def get_initial(self):
        g = self.request.GET
        initial = {k: g[k] for k in ('part', 'task', 'move_type') if g.get(k)}
        if g.get('task') and 'move_type' not in initial:
            initial['move_type'] = StockMove.Type.OUT
        return initial

    def form_valid(self, form):
        move = form.save(self.request.user)
        messages.success(self.request, f'Recorded: {move}. On hand: {move.part.quantity_on_hand} {move.part.unit}.')
        next_url = self.request.GET.get('next')
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={self.request.get_host()}):
            return redirect(next_url)
        return redirect(move.part)


# -- Categories (nested, with attribute definitions) --------------------------

class CategoryListView(LoginRequiredMixin, ListView):
    model = Category
    template_name = 'inventory/tree_list.html'

    def get_queryset(self):
        return sorted_by_path(Category.objects.select_related('parent').annotate(
            part_count=Count('parts', distinct=True), attribute_count=Count('attributes', distinct=True),
        ))

    def get_context_data(self, **kwargs):
        return super().get_context_data(
            **kwargs, heading='Categories', create_url=reverse('inventory:category_create'),
            filter_param='category', show_attributes=True,
        )


@login_required
def category_form(request, pk=None):
    category = get_object_or_404(Category, pk=pk) if pk else Category()
    form = CategoryForm(request.POST or None, instance=category)
    formset = AttributeFormSet(request.POST or None, instance=category, prefix='attrs')
    if request.method == 'POST' and form.is_valid() and formset.is_valid():
        with transaction.atomic():
            category = form.save()
            formset.instance = category
            formset.save()
        messages.success(request, 'Category saved.')
        return redirect('inventory:category_list')
    return render(request, 'inventory/category_form.html', {
        'form': form, 'formset': formset, 'category': category,
        'heading': f'Edit {category}' if pk else 'New category',
    })


# -- Locations (nested) --------------------------------------------------------

class LocationListView(LoginRequiredMixin, ListView):
    model = Location
    template_name = 'inventory/tree_list.html'

    def get_queryset(self):
        return sorted_by_path(Location.objects.select_related('parent').annotate(part_count=Count('parts')))

    def get_context_data(self, **kwargs):
        return super().get_context_data(
            **kwargs, heading='Locations', create_url=reverse('inventory:location_create'), filter_param='location',
        )


class LocationCreateView(LoginRequiredMixin, CreateView):
    model = Location
    form_class = LocationForm
    template_name = 'core/form.html'
    success_url = reverse_lazy('inventory:location_list')
    extra_context = {'heading': 'New location'}


class LocationUpdateView(LoginRequiredMixin, UpdateView):
    model = Location
    form_class = LocationForm
    template_name = 'core/form.html'
    success_url = reverse_lazy('inventory:location_list')

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs, heading=f'Edit {self.object}', cancel_url=self.success_url)
