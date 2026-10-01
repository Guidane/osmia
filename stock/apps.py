from core.modules import MenuItem, Module, OsmiaModuleConfig


class StockConfig(OsmiaModuleConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'stock'
    manifest = Module(
        title='Stock',
        description='How many of each part are where: locations, receipts, issues, counts and moves.',
        icon='🏷️',
        sequence=32,
        depends=('users', 'tasks', 'inventory'),
        menu=(
            MenuItem('Stock', 'stock:list'),
            MenuItem('Moves', 'stock:move_list'),
            MenuItem('Locations', 'stock:location_list'),
            MenuItem('New move', 'stock:move_create'),
        ),
    )
