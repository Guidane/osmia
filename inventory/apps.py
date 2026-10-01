from core.modules import MenuItem, Module, OsmiaModuleConfig


class InventoryConfig(OsmiaModuleConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'inventory'
    manifest = Module(
        title='Parts',
        description='The parts catalogue: descriptions, categories and attributes, and which parts and tools go together.',
        icon='📦',
        sequence=30,
        depends=('users', 'tools'),
        menu=(
            MenuItem('Parts', 'inventory:part_list'),
            MenuItem('Categories', 'inventory:category_list'),
            MenuItem('New part', 'inventory:part_create'),
        ),
    )
