from core.modules import MenuItem, Module, OsmiaModuleConfig


class OrdersConfig(OsmiaModuleConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'orders'
    manifest = Module(
        title='Orders',
        description='Purchase orders against budgets; receiving books the parts into stock.',
        icon='🧾',
        sequence=35,
        depends=('users', 'inventory', 'budgets'),
        menu=(
            MenuItem('Orders', 'orders:list'),
            MenuItem('New order', 'orders:create'),
        ),
    )
