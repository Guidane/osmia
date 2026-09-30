import json
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, F, Q, Sum
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DetailView, FormView, ListView, UpdateView

from core import hooks
from core.trees import link_parents, sorted_by_path

from . import lookup
from .forms import AttributeFormSet, CategoryForm, LocationForm, PartForm, StockMoveForm
from .models import Attribute, Category, Location, Part, StockMove


class PartListView(LoginRequiredMixin, ListView):
    model = Part
    paginate_by = 50

    def get_queryset(self):
        qs = Part.objects.select_related('category__parent', 'location__parent').prefetch_related('images')
        g = self.request.GET
        for word in g.get('q', '').split():
            qs = qs.filter(
                Q(part_number__icontains=word) | Q(name__icontains=word)
                | Q(category__name__icontains=word) | Q(location__name__icontains=word)
                | Q(location__code__iexact=word)
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
            moves=self.object.moves.select_related('user', 'task', 'from_location', 'to_location')[:50],
            move_locations=move_locations(),
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


def move_locations():
    """Every location, in tree order, for "move to" pickers."""
    return sorted_by_path(link_parents(Location.objects.all()))


class MoveListView(LoginRequiredMixin, ListView):
    model = StockMove
    paginate_by = 100

    def get_queryset(self):
        qs = StockMove.objects.select_related('part__location', 'task', 'user', 'from_location', 'to_location')
        if self.request.GET.get('type') in StockMove.Type.values:
            qs = qs.filter(move_type=self.request.GET['type'])
        return qs

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs, types=StockMove.Type.choices, move_locations=move_locations())


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
        nodes = link_parents(Location.objects.prefetch_related('images').annotate(
            own_parts=Count('parts'), own_quantity=Sum('parts__quantity_on_hand'),
        ))
        # Totals include sub-locations, like the part list's location filter.
        for n in nodes:
            n.part_count, n.quantity, n.sub_count = 0, Decimal(0), 0
        for n in nodes:
            for i, a in enumerate(reversed(n.ancestors())):
                a.part_count += n.own_parts
                a.quantity += n.own_quantity or 0
                if i:
                    a.sub_count += 1
        return sorted_by_path(nodes)

    def get_context_data(self, **kwargs):
        return super().get_context_data(
            **kwargs, heading='Locations', create_url=reverse('inventory:location_create'), filter_param='location',
            show_images=True, show_codes=True, show_stock=True,
        )


class LocationDetailView(LoginRequiredMixin, DetailView):
    model = Location

    def get_context_data(self, **kwargs):
        loc = self.object
        return super().get_context_data(
            **kwargs,
            children=sorted_by_path(loc.children.annotate(part_count=Count('parts'))),
            parts=loc.parts.select_related('category').prefetch_related('images'),
            move_locations=move_locations(),
        )


class LocationCreateView(LoginRequiredMixin, CreateView):
    model = Location
    form_class = LocationForm
    template_name = 'core/form.html'
    success_url = reverse_lazy('inventory:location_list')
    extra_context = {'heading': 'New location'}

    def get_initial(self):
        return {'parent': self.request.GET.get('parent')}


class LocationUpdateView(LoginRequiredMixin, UpdateView):
    model = Location
    form_class = LocationForm
    template_name = 'core/form.html'

    def get_success_url(self):
        return self.object.get_absolute_url()

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs, heading=f'Edit {self.object}', cancel_url=self.object.get_absolute_url())


@login_required
def location_generate(request, pk=None):
    """Make a block of sub-locations at once, e.g. rack rows × racks × shelves."""
    from . import locations as gen

    parent = get_object_or_404(Location, pk=pk) if pk else None
    rows = [{'name': 'Rack row', 'count': 4, 'style': 'A', 'start': ''},
            {'name': 'Rack', 'count': 6, 'style': '1', 'start': ''},
            {'name': 'Shelf', 'count': 4, 'style': 'A', 'start': ''}]
    errors = []
    if request.method == 'POST':
        rows = [{key: request.POST.get(f'level-{i}-{key}', '') for key in ('name', 'count', 'style', 'start')}
                for i in range(gen.MAX_LEVELS + 2)]
        rows = [r for r in rows if r['name'].strip() or r['count'].strip()]
        chosen = request.POST.get('parent')
        parent = Location.objects.filter(pk=chosen).first() if chosen else None
        try:
            levels = gen.clean_levels(rows)
        except ValidationError as exc:
            errors = exc.messages
        else:
            created, existing = gen.generate(parent, levels)
            note = f' ({existing} already existed and were kept)' if existing else ''
            messages.success(request, f'Created {created} location{"s" if created != 1 else ""}{note}.')
            return redirect(parent.get_absolute_url() if parent else reverse('inventory:location_list'))
    all_locations = sorted_by_path(Location.objects.all())
    return render(request, 'inventory/location_generate.html', {
        'parent': parent, 'rows': rows, 'errors': errors, 'styles': gen.STYLES,
        'locations': all_locations,
        'codes': {str(loc.pk): loc.code for loc in all_locations},
        'max_locations': gen.MAX_LOCATIONS,
    })


@login_required
def location_delete(request, pk):
    """Delete a location and its sub-locations, but only while no parts are kept in any of them."""
    loc = get_object_or_404(Location, pk=pk)
    ids = {loc.pk, *loc.descendant_ids()}
    parts = Part.objects.filter(location_id__in=ids).select_related('location')
    if request.method == 'POST' and not parts.exists():
        parent = loc.parent
        doomed = list(Location.objects.filter(pk__in=ids))
        with transaction.atomic():
            # Children first: a location with sub-locations can't be deleted before them.
            for node in sorted(doomed, key=lambda n: n.full_path().count(' > '), reverse=True):
                node.delete()
        messages.success(request, f'Deleted {loc.full_path()}' + (f' and {len(ids) - 1} sub-location{"s" if len(ids) != 2 else ""}.' if len(ids) > 1 else '.'))
        back = request.POST.get('next') or ''
        if url_has_allowed_host_and_scheme(back, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            return redirect(back)
        return redirect(parent.get_absolute_url() if parent else reverse('inventory:location_list'))
    return render(request, 'inventory/location_delete.html', {
        'location': loc, 'sub_count': len(ids) - 1, 'parts': parts[:50], 'part_count': parts.count(),
    })


@login_required
@require_POST
def transfer(request):
    """Move the selected parts' stock to another location (from the stock moves
    list, a location's parts or a part's page)."""
    back = request.POST.get('next') or ''
    if not url_has_allowed_host_and_scheme(back, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        back = reverse('inventory:move_list')
    location = Location.objects.filter(pk=request.POST.get('location') or None).first()
    ids = {int(p) for p in request.POST.getlist('parts') if p.isdigit()}
    if location is None:
        messages.error(request, 'Pick the location to move to.')
        return redirect(back)
    if not ids:
        messages.error(request, 'Select the rows to move first.')
        return redirect(back)
    moved, already = [], 0
    with transaction.atomic():
        for part in Part.objects.filter(pk__in=ids).select_related('location'):
            if StockMove.transfer(part, location, user=request.user, note=request.POST.get('note', '').strip()[:255]):
                moved.append(part.part_number)
            else:
                already += 1
    where = f'{location.code} ({location.name})' if location.code else location.full_path()
    if moved:
        shown = ', '.join(moved[:5]) + (f' and {len(moved) - 5} more' if len(moved) > 5 else '')
        messages.success(request, f'Moved {shown} to {where}.')
    if already:
        messages.info(request, f'{already} part{"s were" if already != 1 else " was"} already in {where}.')
    return redirect(back)
