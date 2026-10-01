from core.modules import MenuItem, Module, OsmiaModuleConfig


class AssembliesConfig(OsmiaModuleConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'assemblies'
    manifest = Module(
        title='Assemblies',
        description='Bills of materials built from parts and sub-assemblies.',
        icon='🧩',
        sequence=40,
        depends=('inventory', 'stock', 'tasks'),
        menu=(
            MenuItem('Assemblies', 'assemblies:list'),
            MenuItem('New assembly', 'assemblies:create'),
        ),
    )
