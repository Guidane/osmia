from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def home(request):
    """The landing page: just the installed modules."""
    return render(request, 'core/home.html')
