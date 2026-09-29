from core.modules import MenuItem, Module, OsmiaModuleConfig


class UsersConfig(OsmiaModuleConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'users'
    manifest = Module(
        title='Users',
        description='People and access.',
        depends=('departments',),
        icon='👥',
        sequence=10,
        menu=(
            MenuItem('All users', 'users:list'),
            MenuItem('New user', 'users:create'),
        ),
    )
