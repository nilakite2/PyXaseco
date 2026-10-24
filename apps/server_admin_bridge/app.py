"""Optional dedicated-server login authorization for internal admin tooling."""

from pyxaseco.core.base import App

from . import service


APP_METADATA = {
    'id': 'server_admin_bridge',
    'display_name': 'Server Admin Bridge',
    'description': 'Optional internal tooling: authorize the dedicated-server login as MasterAdmin.',
    'modules': ['apps/server_admin_bridge/app.py', 'apps/server_admin_bridge/service.py'],
    'entries': ['app/server_admin_bridge'],
    'provides': ['bridge/server_admin_bridge'],
    'depends_on': ['admin'],
}


class ServerAdminBridgeApp(App):
    def __init__(self):
        super().__init__(app_id='server_admin_bridge', display_name='Server Admin Bridge',
                         description=APP_METADATA['description'], depends_on=('admin',),
                         entry_modules=('app/server_admin_bridge',))

    def register_runtime(self, aseco):
        service.register(aseco)


APP_CLASS = ServerAdminBridgeApp
APP_INSTANCE = ServerAdminBridgeApp()


def register(aseco):
    APP_INSTANCE.register_runtime(aseco)
