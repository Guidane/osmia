from core.modules import MenuItem, Module, OsmiaModuleConfig


class BudgetsConfig(OsmiaModuleConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'budgets'
    manifest = Module(
        title='Budgets',
        description='Department budgets and what tasks spend against them.',
        icon='💰',
        sequence=50,
        depends=('users', 'tasks'),
        menu=(
            MenuItem('Budgets', 'budgets:list'),
            MenuItem('New budget', 'budgets:create'),
        ),
    )
