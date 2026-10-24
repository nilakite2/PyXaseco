"""Personal chat visibility merged with administrator restrictions."""

from .widget_delivery import deliver_ui


def overrides(aseco):
    if not hasattr(aseco, '_chat_visibility_overrides'):
        aseco._chat_visibility_overrides = {}
    return aseco._chat_visibility_overrides


def visible(aseco, login, default=True):
    values = overrides(aseco).get(login, {})
    # A personal 'on' must never bypass an administrator's 'off'.
    return all(values.values()) if values else bool(default)


def forget(aseco, login, owner):
    values = overrides(aseco).get(login)
    if values is not None:
        values.pop(owner, None)
        if not values:
            overrides(aseco).pop(login, None)


async def set_override(aseco, login, owner, value):
    if value is None:
        forget(aseco, login, owner)
    else:
        overrides(aseco).setdefault(login, {})[owner] = bool(value)
    if aseco.server.players.get_player(login) is None:
        return
    lookup = getattr(aseco, 'get_service', None)
    renderer = lookup('ui/custom_ui') if callable(lookup) else None
    if callable(renderer):
        await renderer(aseco, login)
        return
    # Without the HUD app, change only native chat visibility.
    value = 'true' if visible(aseco, login) else 'false'
    xml = ('<manialinks><manialink id="0"><line/></manialink>'
           f'<custom_ui><chat visible="{value}"/></custom_ui></manialinks>')
    await deliver_ui(aseco, 'SendDisplayManialinkPageToLogin', login, xml, 0, False)
