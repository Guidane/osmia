from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import Count, F, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from assemblies.models import Assembly
from core import hooks

from .forms import ConnectorForm, DeviceForm, PinFormSet
from .models import Connector, Device, Pin


class DeviceListView(LoginRequiredMixin, ListView):
    model = Device

    def get_queryset(self):
        qs = Device.objects.select_related('responsible', 'assembly').annotate(
            connector_count=Count('connectors', distinct=True), pin_count=Count('connectors__pins'),
        )
        g = self.request.GET
        if g.get('q'):
            qs = qs.filter(
                Q(name__icontains=g['q']) | Q(part_number__icontains=g['q']) | Q(manufacturer__icontains=g['q'])
                | Q(model_number__icontains=g['q']) | Q(asset_tag__icontains=g['q'])
            )
        if g.get('origin') in Device.Origin.values:
            qs = qs.filter(origin=g['origin'])
        if g.get('role') in Device.Role.values:
            qs = qs.filter(role=g['role'])
        return qs

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs, origins=Device.Origin.choices, roles=Device.Role.choices)


class DeviceDetailView(LoginRequiredMixin, DetailView):
    model = Device

    def get_context_data(self, **kwargs):
        d = self.object
        connectors = d.connectors.select_related('part').prefetch_related('pins')
        return super().get_context_data(
            **kwargs,
            connectors=connectors,
            versions=d.versions.select_related('created_by')[:20],
            panels=hooks.collect('device_detail_panels', self.request, d),
        )


class DeviceFormMixin(LoginRequiredMixin):
    model = Device
    form_class = DeviceForm
    template_name = 'core/form.html'

    def form_valid(self, form):
        with transaction.atomic():
            response = super().form_valid(form)
            self.object.snapshot(self.request.user)
        messages.success(self.request, 'Device saved.')
        return response


class DeviceCreateView(DeviceFormMixin, CreateView):
    extra_context = {'heading': 'New device'}

    def get_initial(self):
        g = self.request.GET
        initial = {'responsible': self.request.user}
        if g.get('origin') == Device.Origin.EXTERNAL:
            initial.update(origin=Device.Origin.EXTERNAL, role=Device.Role.POWER_SUPPLY)
        return initial


class DeviceUpdateView(DeviceFormMixin, UpdateView):
    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs, heading=f'Edit {self.object}', cancel_url=self.object.get_absolute_url())


@login_required
@require_POST
def device_from_assembly(request, assembly_pk):
    """Create the device record for an assembly of type "Device"."""
    assembly = get_object_or_404(Assembly, pk=assembly_pk, assembly_type=Assembly.Type.DEVICE)
    device = getattr(assembly, 'device', None)
    if device is None:
        device = Device.objects.create(name=assembly.name, assembly=assembly, responsible=request.user)
        device.snapshot(request.user)
        messages.success(request, 'Device created. Now add its connectors.')
    return redirect(device)


@login_required
def connector_form(request, device_pk, pk=None):
    device = get_object_or_404(Device, pk=device_pk)
    if pk:
        connector = get_object_or_404(Connector, pk=pk, device=device)
    else:
        n = device.connectors.count() + 1
        connector = Connector(device=device, position=n, designator=f'J{n:02d}')
    form = ConnectorForm(request.POST or None, instance=connector, initial=None if pk else {'add_pins': 2})
    formset = PinFormSet(request.POST or None, instance=connector, prefix='pins')
    if request.method == 'POST' and form.is_valid() and formset.is_valid():
        with transaction.atomic():
            connector = form.save()
            formset.instance = connector
            formset.save(commit=False)
            for pin in formset.deleted_objects:
                pin.delete()
            deleted = set(formset.deleted_forms)
            pins = [f.instance for f in formset.forms if f not in deleted and (f.instance.pk or f.has_changed())]
            # Renumber in the order shown, clear of the unique (connector, position) constraint.
            Pin.objects.filter(connector=connector).update(position=F('position') + 100000)
            for i, pin in enumerate(pins, start=1):
                pin.connector, pin.position = connector, i
                pin.save()
            for i in range(len(pins) + 1, len(pins) + 1 + (form.cleaned_data.get('add_pins') or 0)):
                Pin.objects.create(connector=connector, position=i, label=str(i))
            new_version = device.snapshot(request.user)
        messages.success(request, f'{connector.designator} saved.' + (f' Device is now v{device.version}.' if new_version else ''))
        if request.POST.get('continue'):
            return redirect('devices:connector_edit', device.pk, connector.pk)
        return redirect(device)
    return render(request, 'devices/connector_form.html', {
        'device': device, 'connector': connector, 'form': form, 'formset': formset,
        'heading': f'{device.name} · {connector.designator}' if pk else f'{device.name} · new connector',
    })


@login_required
@require_POST
def connector_delete(request, device_pk, pk):
    device = get_object_or_404(Device, pk=device_pk)
    connector = get_object_or_404(Connector, pk=pk, device=device)
    with transaction.atomic():
        connector.delete()
        device.snapshot(request.user)
    messages.success(request, f'{connector.designator} removed.')
    return redirect(device)


@login_required
@require_POST
def activate_version(request, pk, version):
    device = get_object_or_404(Device, pk=pk)
    device.activate_version(version)
    messages.success(request, f'Version {version} is current again.')
    return redirect(device)
