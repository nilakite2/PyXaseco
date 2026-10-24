from pyxaseco.app_config import clear_app_defaults_cache
from pyxaseco.core.base import App

from . import service


APP_METADATA = {
    'id': 'records_ultimania', 'display_name': 'Ultimania Records',
    'description': 'Optional Ultimania v5 Stunts records, score submissions and replays in the shared records slot.',
    'modules': ['apps/records_ultimania/service.py', 'apps/records_ultimania/api.py',
                'apps/records_ultimania/records_widget.py'],
    'entries': ['app/records_ultimania'], 'provides': ['service/records_ultimania'],
    'depends_on': ['platform_core', 'ui'],
}


class RecordsUltimaniaApp(App):
    def __init__(self):
        super().__init__(app_id='records_ultimania', display_name='Ultimania Records',
                         description=APP_METADATA['description'], depends_on=('platform_core', 'ui'),
                         entry_modules=('app/records_ultimania',), settings_schema=service.SCHEMA)

    async def startup(self, context):
        service.RUNTIME.configure(context.aseco)

    async def shutdown(self, _context):
        service.RUNTIME.enabled = False


APP_CLASS = RecordsUltimaniaApp


def register(aseco):
    service.RUNTIME.register(aseco)


async def reload_runtime(aseco):
    clear_app_defaults_cache(getattr(aseco, '_base_dir', None))
    service.RUNTIME.configure(aseco)
    await service.RUNTIME.sync(aseco)
