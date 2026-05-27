from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.app_config import AppSetting, AppSettingsSchema, as_bool, bind_app_settings
from pyxaseco.core.base import Component

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


STALKER_ACTIONIDS_SETTINGS_SCHEMA = AppSettingsSchema(
    app_id='admin',
    section_name='admin',
    description='Optional Stalker action-id bridge settings',
    settings=(
        AppSetting('stalker_actionids/enabled', False, as_bool, 'Enable the optional Stalker action-id bridge.', 'stalker'),
    ),
)

feature_stalker_actionids = False
_ACTION_COMMANDS: dict[int, str] = {
    27008505: '/st chatall',
    270085052: '/jfreu players live',
    270085053: '/music list',
    270085054: '/list',
}


def _apply_app_defaults(aseco: 'Aseco') -> None:
    global feature_stalker_actionids
    bound = bind_app_settings(STALKER_ACTIONIDS_SETTINGS_SCHEMA, getattr(aseco, '_base_dir', None))
    feature_stalker_actionids = bool(bound.values['stalker_actionids/enabled'])
    setattr(aseco, 'feature_stalker_actionids', feature_stalker_actionids)
    setattr(aseco.server, 'feature_stalker_actionids', feature_stalker_actionids)


def register(aseco: 'Aseco'):
    _apply_app_defaults(aseco)
    if not feature_stalker_actionids:
        return
    aseco.register_event('onPlayerManialinkPageAnswer', _event_stalker_actionids)


async def _event_stalker_actionids(aseco: 'Aseco', command: list):
    if len(command) < 3:
        return
    login = str(command[1] or '').strip()
    if not login:
        return
    try:
        action = int(command[2])
    except Exception:
        return
    chat_command = _ACTION_COMMANDS.get(action)
    if not chat_command:
        return
    await aseco.dispatch_chat_command(login, chat_command)


class StalkerActionIdsSurface(Component):
    def __init__(self):
        super().__init__(
            component_id='admin.stalker_actionids',
            description='Optional Stalker action-id bridge surface.',
        )

    def register(self, aseco) -> None:
        register(aseco)


SURFACE = StalkerActionIdsSurface()


def get_component() -> StalkerActionIdsSurface:
    return SURFACE
