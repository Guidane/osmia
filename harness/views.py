"""The harness designer page and the JSON API it talks to.

The API keeps the stand-alone designer's shapes (see harness/static/harness/
designer.js), so the editor works unchanged; devices and users now come from
Osmia's Devices and Users modules.
"""
import json

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from django.views.generic import ListView

from devices.models import Device

from .models import HarnessProject, SignalRule


class ProjectListView(LoginRequiredMixin, ListView):
    model = HarnessProject
    template_name = 'harness/harnessproject_list.html'  # the queryset becomes a list

    def get_queryset(self):
        projects = list(HarnessProject.objects.select_related('created_by'))
        for p in projects:
            p.counts = p.stats()
        return projects


@login_required
def designer(request):
    return render(request, 'harness/designer.html', {
        'api_base': reverse('harness:api_devices').removesuffix('/devices'),
        'users_url': reverse('users:list'),
        'devices_url': reverse('devices:list'),
    })


def _json_body(request):
    try:
        return json.loads(request.body or b'{}')
    except ValueError:
        return None


# -- Devices -------------------------------------------------------------------

@login_required
@require_http_methods(['GET', 'POST'])
def api_devices(request):
    if request.method == 'GET':
        devices = Device.objects.prefetch_related('connectors__pins')
        return JsonResponse([d.to_harness() for d in devices], safe=False)
    data = _json_body(request)
    if not isinstance(data, dict):
        return HttpResponseBadRequest('Expected a JSON object.')
    if data.get('id'):
        device = get_object_or_404(Device, pk=data['id'])
    else:
        origin = data.get('origin') if data.get('origin') in Device.Origin.values else Device.Origin.IN_HOUSE
        device = Device(origin=origin, role=Device.Role.PRODUCT if origin == Device.Origin.IN_HOUSE else Device.Role.OTHER)
    if data.get('origin') in Device.Origin.values:
        device.origin = data['origin']
    device.apply_definition(data)
    device.snapshot(request.user)
    return JsonResponse(device.to_harness())


@login_required
def api_device(request, pk):
    device = get_object_or_404(Device, pk=pk)
    version = request.GET.get('version')
    if version:
        snap = device.versions.filter(version=version).first()
        if snap is None:
            raise Http404
        return JsonResponse({**snap.data, 'id': str(device.pk), 'version': snap.version, 'url': device.get_absolute_url()})
    return JsonResponse(device.to_harness())


@login_required
def api_device_versions(request, pk):
    device = get_object_or_404(Device, pk=pk)
    return JsonResponse({'versions': sorted(device.versions.values_list('version', flat=True))})


@login_required
@require_http_methods(['POST'])
def api_device_activate(request, pk, version):
    device = get_object_or_404(Device, pk=pk)
    if not device.versions.filter(version=version).exists():
        return JsonResponse({'error': 'version not found'}, status=404)
    device.activate_version(version)
    return JsonResponse(device.to_harness())


# -- Projects ------------------------------------------------------------------

@login_required
@require_http_methods(['GET', 'POST'])
def api_projects(request):
    if request.method == 'GET':
        return JsonResponse([p.to_designer() for p in HarnessProject.objects.prefetch_related('versions')], safe=False)
    data = _json_body(request)
    if not isinstance(data, dict):
        return HttpResponseBadRequest('Expected a JSON object.')
    project = HarnessProject.objects.filter(pk=data.get('id') or None).first() or HarnessProject(created_by=request.user)
    project.save_version(data, request.user)
    return JsonResponse(project.to_designer())


@login_required
@require_http_methods(['GET', 'DELETE'])
def api_project(request, pk):
    project = get_object_or_404(HarnessProject, pk=pk)
    if request.method == 'DELETE':
        project.delete()
        return JsonResponse({'deleted': True})
    version = request.GET.get('version')
    if version and not project.versions.filter(version=version).exists():
        raise Http404
    return JsonResponse(project.to_designer(int(version) if version else None))


@login_required
def api_project_versions(request, pk):
    project = get_object_or_404(HarnessProject, pk=pk)
    return JsonResponse({'versions': sorted(project.versions.values_list('version', flat=True))})


@login_required
@require_http_methods(['POST'])
def api_project_activate(request, pk, version):
    project = get_object_or_404(HarnessProject, pk=pk)
    if not project.versions.filter(version=version).exists():
        return JsonResponse({'error': 'version not found'}, status=404)
    project.version = version
    project.name = project.data(version).get('name') or project.name
    project.save(update_fields=['version', 'name', 'updated_at'])
    return JsonResponse(project.to_designer())


# -- Settings ------------------------------------------------------------------

@login_required
@require_http_methods(['GET', 'POST'])
def api_signal_rules(request):
    if request.method == 'POST':
        data = _json_body(request)
        if not isinstance(data, dict) or not isinstance(data.get('pairs', []), list):
            return HttpResponseBadRequest('Expected {"pairs": [[a, b], ...]}.')
        SignalRule.replace_all(p for p in data.get('pairs', []) if isinstance(p, list) and len(p) == 2)
    return JsonResponse({'pairs': SignalRule.pairs()})


@login_required
def api_users(request):
    """Osmia's users, in the designer's {id, name} format (read-only here)."""
    users = get_user_model().objects.filter(is_active=True)
    return JsonResponse({'users': [{'id': str(u.pk), 'name': str(u)} for u in users]})
