from core.modules import MenuItem, Module, OsmiaModuleConfig


class UsersConfig(OsmiaModuleConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'users'
    manifest = Module(
        title='Users',
        description='People, departments and access.',
        icon='👥',
        sequence=10,
        menu=(
            MenuItem('All users', 'users:list'),
            MenuItem('Departments', 'users:department_list'),
            MenuItem('New user', 'users:create'),
        ),
    )
