from core.modules import MenuItem, Module, OsmiaModuleConfig


class HarnessConfig(OsmiaModuleConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'harness'
    manifest = Module(
        title='Harness',
        description='Wire harness designer: connect device connectors pin by pin.',
        icon='🧵',
        sequence=46,
        depends=('users', 'devices'),
        menu=(
            MenuItem('Projects', 'harness:list'),
            MenuItem('Designer', 'harness:designer'),
        ),
    )
