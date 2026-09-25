from importlib import import_module
from importlib.util import find_spec

from django.core.management.base import BaseCommand
from django.db import transaction

from core.modules import dependency_order


class Command(BaseCommand):
    help = "Load demo data from every installed module's demo.py, in dependency order."

    @transaction.atomic
    def handle(self, *args, **options):
        for config in dependency_order():
            if find_spec(f"{config.name}.demo") is None:
                continue
            import_module(f"{config.name}.demo").load()
            self.stdout.write(f"  loaded demo data for {config.label}")
        self.stdout.write(self.style.SUCCESS("Demo data loaded. Log in as admin / admin."))
