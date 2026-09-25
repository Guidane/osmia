from django.urls import reverse

from core import hooks

from .forms import LinkTaskForm
from .models import Assembly, AssemblyComponent, TaskLink


@hooks.register('dashboard_widgets')
def in_manufacturing(request):
    count = Assembly.objects.filter(status=Assembly.Status.MANUFACTURING).count()
    return hooks.Widget('Assemblies in manufacturing', count, reverse('assemblies:list') + '?status=manufacturing')


@hooks.register('task_detail_panels')
def task_assembly(request, task):
    link = TaskLink.objects.filter(task=task).select_related('assembly').first()
    assembly = link.assembly if link else None
    totals = assembly.total_parts() if assembly else []
    return hooks.panel('Assembly', 'assemblies/_task_panel.html', {
        'task': task,
        'assembly': assembly,
        'totals': totals,
        'short': [r for r in totals if r['short']],
        'form': LinkTaskForm(initial={'assembly': assembly}),
    }, request, order=5)


@hooks.register('part_detail_panels')
def part_used_in(request, part):
    uses = AssemblyComponent.objects.filter(part=part).select_related('assembly')
    return hooks.panel('Used in assemblies', 'assemblies/_part_panel.html', {'uses': uses}, request)
