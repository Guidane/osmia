from django.apps import apps
from django.urls import reverse

from . import hooks
from .modules import get_module, installed_modules


def osmia(request):
    match = getattr(request, 'resolver_match', None)
    current = get_module(match.namespace) if match and match.namespace else None
    log_url = ''
    if current is not None and current.label != 'audit' and apps.is_installed('audit'):
        log_url = reverse('audit:list') + f'?module={current.label}'
    return {
        'osmia_modules': installed_modules(),
        'current_module': current,
        'module_log_url': log_url,  # the Audit module's log of this module
        # e.g. the notifications bell from Automations
        'topbar_items': hooks.collect('topbar_items', request) if request.user.is_authenticated else [],
    }
