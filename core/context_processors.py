from .modules import get_module, installed_modules


def osmia(request):
    match = getattr(request, 'resolver_match', None)
    current = get_module(match.namespace) if match and match.namespace else None
    return {
        'osmia_modules': installed_modules(),
        'current_module': current,
    }
