from pyxaseco.core.base import App

from .service import LocalBridge


APP_METADATA = {
    'id': 'management_bridge',
    'display_name': 'Local Management Bridge',
    'description': 'Optional authenticated loopback administration for this controller.',
    'depends_on': ['platform_core'],
    'entries': ['app/management_bridge'],
    'provides': ['service/management.runtime'],
}


class ManagementBridgeApp(App):
    def __init__(self):
        super().__init__(app_id='management_bridge', display_name='Local Management Bridge')
        self.bridge = None

    def register_runtime(self, aseco):
        aseco.register_event('onMainLoop', self._tick)
        aseco.register_event('onShutdown', self._closing)

    async def startup(self, context):
        from pyxaseco.app_config import load_app_defaults_file
        data, _ = load_app_defaults_file('management_bridge', context.base_dir)
        config = data.get('management_bridge', {})
        self.bridge = LocalBridge(context.aseco, host=config.get('host', '127.0.0.1'), port=config.get('port', 0))
        try:
            await self.bridge.start()
            context.aseco.register_service('management.runtime', self.bridge.runtime, owner='management_bridge')
        except BaseException:
            await self.bridge.close()
            self.bridge = None
            raise

    async def _tick(self, _aseco, _param):
        if self.bridge:
            await self.bridge.runtime.tick()

    def _closing(self, _aseco, _param):
        if self.bridge:
            self.bridge.runtime.mark_closing()

    async def shutdown(self, _context):
        if self.bridge:
            await self.bridge.close()


APP_CLASS = ManagementBridgeApp
APP_INSTANCE = ManagementBridgeApp()


def register(aseco):
    APP_INSTANCE.register_runtime(aseco)
