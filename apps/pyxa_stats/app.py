"""Optional external statistics publishing, independent of Server Info."""

from pyxaseco.app_config import clear_app_defaults_cache
from pyxaseco.core.base import App
from . import service
from .service import SCHEMA, validate_config


APP_METADATA = {
    'id': 'pyxa_stats', 'display_name': 'PYXA Stats',
    'description': 'Optional API publishing of server snapshots and recent local records.',
    'modules': ['apps/pyxa_stats/app.py', 'apps/pyxa_stats/service.py'],
    'entries': ['app/pyxa_stats'],
    'provides': ['bridge/pyxa_stats', 'bridge/public_stats'],
    'depends_on': ['platform_core', 'records_local'],
}


class PyxaStatsApp(App):
    def __init__(self):
        super().__init__(app_id='pyxa_stats', display_name='PYXA Stats',
                         description=APP_METADATA['description'], depends_on=('platform_core', 'records_local'),
                         entry_modules=('app/pyxa_stats',), settings_schema=SCHEMA)

    def register_runtime(self, aseco):
        service.register(aseco)

    async def startup(self, context):
        await service.public_stats_startup(context.aseco)
        await service._post_heartbeat(context.aseco, force=True)

    async def shutdown(self, _context):
        service._enabled = False
        service._pending_heartbeat = None


APP_CLASS = PyxaStatsApp
APP_INSTANCE = PyxaStatsApp()


def register(aseco):
    APP_INSTANCE.register_runtime(aseco)


async def reload_runtime(aseco):
    clear_app_defaults_cache(getattr(aseco, '_base_dir', None))
    service.configure(aseco)
    service._pending_heartbeat = None
    aseco.jobs.service('public_stats_heartbeat', service.HEARTBEAT_POLICY).invalidate()
    if service._is_enabled():
        service._stats_delivery(aseco)
        await service._post_heartbeat(aseco, force=True)
