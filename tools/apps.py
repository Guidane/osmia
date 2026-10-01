from core.modules import MenuItem, Module, OsmiaModuleConfig


class ToolsConfig(OsmiaModuleConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'tools'
    manifest = Module(
        title='Tools',
        description='Crimp tools, insertion tools, meters and the like, and which parts they are used with.',
        icon='🛠️',
        sequence=28,
        depends=('users',),
        menu=(
            MenuItem('Tools', 'tools:list'),
            MenuItem('New tool', 'tools:create'),
        ),
    )
