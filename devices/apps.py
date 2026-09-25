from core.modules import MenuItem, Module, OsmiaModuleConfig


class DevicesConfig(OsmiaModuleConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'devices'
    manifest = Module(
        title='Devices',
        description='Electrical devices, ours and external, with their connectors and pins.',
        icon='🔌',
        sequence=45,
        depends=('users', 'inventory', 'assemblies'),
        menu=(
            MenuItem('Devices', 'devices:list'),
            MenuItem('New device', 'devices:create'),
        ),
    )
