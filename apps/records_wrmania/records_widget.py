"""Mania Records in the existing Classic/Modern external-record slot."""

from dataclasses import replace

from pyxaseco.helpers import _send_multipage, format_time


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
    from apps.ui.config import _state, _effective_mode
    from apps.ui.widgets.common import _hide, _send
    from apps.ui.widgets.records_common import ML_DEDI, _dedi_close_to_you, _build_record_widget

    service = provider(aseco)
    mode = _effective_mode(aseco)
    cfg = _state.dedi.get(mode)
    if (service is None or not cfg or not cfg.enabled or _state.challenge_show_next
            or not _state.player_visible.get(login, True) or not await service.visible(aseco)):
        _state.player_dedi_digest.pop(login, None)
        await _hide(aseco, login, ML_DEDI)
        return
    player = aseco.server.players.get_player(login)
    style = aseco.services.get('ui/uistyle')
    modern = style is not None and style.resolve(player).base == 1
    rows = [row for row in service.rows if row['rank'] <= service.client.limit]
    entries = _dedi_close_to_you(rows, login, cfg.entries, cfg.topcount,
                                getattr(player, 'nickname', login), include_no_record=not modern)
    online = {p.login for p in aseco.server.players.all()} if _state.mark_online else set()
    xml = _build_record_widget(aseco=aseco, ml_id=ML_DEDI, cfg=replace(cfg, title='Mania Records'),
        login=login, entries=entries, online=online, mode=mode, click_action=ACTION)
    digest = str(hash(xml))
    if _state.player_dedi_digest.get(login) != digest:
        await _send(aseco, login, xml)
        _state.player_dedi_digest[login] = digest


async def show_window(aseco, player, rows):
    service = provider(aseco)
    uid, epoch = service.uid, service.epoch
    client, limit = service.client, service.client.limit

    def valid(runtime, _player):
        current = provider(runtime)
        return (current is service and current.active(runtime) and current.uid == uid and current.epoch == epoch
                and current.client is client and client.limit == limit)

    table = [[str(row['rank']), format_time(row['score']), row['nickname'], row['login']]
             for row in rows if row['rank'] <= service.client.limit]
    if not table:
        table = [['-', '-', 'No Mania Records yet.', '']]
    player.msgs = [[1, 'Mania Records', [1.35, .12, .25, .65, .33],
                    ['Icons128x128_1', 'Rankings'], valid]]
    player.msgs.extend([[['Rank', 'Time', 'Player', 'Login']] + table[i:i + 20]
                       for i in range(0, len(table), 20)])
    await _send_multipage(aseco, player)
