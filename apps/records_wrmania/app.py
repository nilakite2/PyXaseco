from pyxaseco.app_config import clear_app_defaults_cache
from pyxaseco.core.base import App

from . import service


APP_METADATA = {
    'id': 'records_wrmania', 'display_name': 'Mania Records',
    'description': 'Optional WRMania submissions and fallback global-record widget.',
    'modules': ['apps/records_wrmania/service.py', 'apps/records_wrmania/api.py',
                'apps/records_wrmania/records_widget.py'],
    'entries': ['app/records_wrmania'], 'provides': ['service/records_wrmania'],
    'depends_on': ['platform_core', 'ui'],
}


class RecordsWRManiaApp(App):
    def __init__(self):
        super().__init__(app_id='records_wrmania', display_name='Mania Records',
            description=APP_METADATA['description'], depends_on=('platform_core', 'ui'),
            entry_modules=('app/records_wrmania',), settings_schema=service.SCHEMA)

    async def startup(self, context):
        service.RUNTIME.configure(context.aseco)

    async def shutdown(self, _context):
        service.RUNTIME.enabled = False


APP_CLASS = RecordsWRManiaApp


def register(aseco):
    service.RUNTIME.register(aseco)


async def reload_runtime(aseco):
    clear_app_defaults_cache(getattr(aseco, '_base_dir', None))
    service.RUNTIME.configure(aseco)
    await service.RUNTIME.sync(aseco)
