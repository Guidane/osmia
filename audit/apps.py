from core.modules import MenuItem, Module, OsmiaModuleConfig


class AuditConfig(OsmiaModuleConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'audit'
    manifest = Module(
        title='Audit',
        description='Every change to every module, who made it, and chains of changes across modules.',
        icon='🔍',
        sequence=95,
        depends=('users',),
        menu=(
            MenuItem('Log', 'audit:list'),
            MenuItem('Chains', 'audit:chains'),
            MenuItem('Activity', 'audit:activity'),
        ),
    )

    def ready(self):
        super().ready()
        from core import audit
        audit.connect()
