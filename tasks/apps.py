from core.modules import MenuItem, Module, OsmiaModuleConfig


class TasksConfig(OsmiaModuleConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'tasks'
    manifest = Module(
        title='Tasks',
        description='Plan and track work across the team.',
        icon='✅',
        sequence=20,
        depends=('users',),
        menu=(
            MenuItem('Board', 'tasks:board'),
            MenuItem('List', 'tasks:list'),
            MenuItem('Gantt', 'tasks:gantt'),
            MenuItem('My tasks', 'tasks:mine'),
            MenuItem('New task', 'tasks:create'),
        ),
    )
