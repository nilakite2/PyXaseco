"""Mania Records in the existing Classic/Modern external-record slot."""

from dataclasses import replace

from apps.platform_ui import record_browser


ACTION = 8590100


def provider(aseco):
    if 'records_wrmania' not in (getattr(aseco, 'active_apps', ()) or ()):
        return None
    return aseco.services.get('service/records_wrmania')


async def _is_wrmania_visible(aseco):
    service = provider(aseco)
    return service is not None and await service.visible(aseco)


async def _open_wrmania_window(aseco, login):
    service = provider(aseco)
    player = aseco.server.players.get_player(login)
    if service is not None and service.active(aseco) and player is not None:
        await show_window(aseco, player, service.rows)


async def _draw_wrmania_player(aseco, login):
    from apps.ui import record_widgets as ui

    service = provider(aseco)
    mode = ui.game_mode(aseco)
    cfg = ui.panel(mode)
    if (service is None or not cfg or not cfg.enabled or ui.shows_next_map()
            or not ui.visible(login) or not await service.visible(aseco)):
        ui.clear_digest(login)
        await ui.hide(aseco, login, ui.ML_DEDI)
        return
    player = aseco.server.players.get_player(login)
    style = aseco.services.get('ui/uistyle')
    modern = style is not None and style.resolve(player).base == 1
    rows = [row for row in service.rows if row['rank'] <= service.client.limit]
    entries = ui.close_to_you(rows, login, cfg.entries, cfg.topcount,
                                getattr(player, 'nickname', login), include_no_record=not modern)
    online = ui.online_logins(aseco)
    xml = ui.build_record_widget(aseco=aseco, ml_id=ui.ML_DEDI, cfg=replace(cfg, title='Mania Records'),
        login=login, entries=entries, online=online, mode=mode, click_action=ACTION)
    digest = str(hash(xml))
    if ui.current_digest(login) != digest:
        await ui.send(aseco, login, xml)
        ui.set_digest(login, digest)


async def show_window(aseco, player, rows):
    service = provider(aseco)
    uid, epoch = service.uid, service.epoch
    client, limit = service.client, service.client.limit

    def valid(runtime, _player):
        current = provider(runtime)
        return (current is service and current.active(runtime) and current.uid == uid and current.epoch == epoch
                and current.client is client and client.limit == limit)

    runs = [record_browser.Run(row['login'], row['nickname'], row['score'], row['rank'],
                               record_browser.split_values(row.get('checkpointsMs')))
            for row in rows if row['rank'] <= limit]
    await record_browser.show(aseco, player, 'Mania Records', runs, valid=valid, show_logins=True)
