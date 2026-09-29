from core.modules import MenuItem, Module, OsmiaModuleConfig


class AutomationsConfig(OsmiaModuleConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'automations'
    manifest = Module(
        title='Automations',
        description='Rules: when something happens (an order is placed), do things (create tasks, notify people).',
        icon='⚡',
        sequence=90,
        depends=('users',),
        menu=(
            MenuItem('Rules', 'automations:list'),
            MenuItem('New rule', 'automations:create'),
            MenuItem('Run log', 'automations:runs'),
            MenuItem('Notifications', 'automations:notifications'),
        ),
    )

    def ready(self):
        super().ready()
        from core import automation

        from . import engine
        automation.subscribe(engine.handle)
