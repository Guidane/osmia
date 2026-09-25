from core.modules import MenuItem, Module, OsmiaModuleConfig


class InventoryConfig(OsmiaModuleConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'inventory'
    manifest = Module(
        title='Inventory',
        description='Parts, stock levels, locations and movements.',
        icon='📦',
        sequence=30,
        depends=('users', 'tasks'),
        menu=(
            MenuItem('Parts', 'inventory:part_list'),
            MenuItem('Stock moves', 'inventory:move_list'),
            MenuItem('Categories', 'inventory:category_list'),
            MenuItem('Locations', 'inventory:location_list'),
            MenuItem('New move', 'inventory:move_create'),
        ),
    )
