from core.modules import MenuItem, Module, OsmiaModuleConfig


class DepartmentsConfig(OsmiaModuleConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'departments'
    manifest = Module(
        title='Departments',
        description='The organisation, as nested departments.',
        icon='🏢',
        sequence=11,
        menu=(
            MenuItem('Departments', 'departments:list'),
            MenuItem('New department', 'departments:create'),
        ),
    )
