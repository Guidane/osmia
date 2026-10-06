from core.modules import MenuItem, Module, OsmiaModuleConfig


class VendorsConfig(OsmiaModuleConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'vendors'
    manifest = Module(
        title='Vendors',
        description='The companies we buy from: contact details, address, account and payment terms.',
        icon='🏢',
        sequence=29,
        depends=('users',),
        menu=(
            MenuItem('Vendors', 'vendors:list'),
            MenuItem('New vendor', 'vendors:create'),
        ),
    )
