"""Cached-only provider views using existing record widgets and paged windows."""

from dataclasses import replace

from pyxaseco.helpers import _send_multipage
from pyxaseco.models import Gameinfo


ACTION = 8590000


def provider(aseco):
    if 'records_ultimania' not in (getattr(aseco, 'active_apps', ()) or ()):
        return None
    service = aseco.services.get('service/records_ultimania')
    return service if service is not None and service.active(aseco) else None


async def _is_ultimania_track_active(aseco):
    return provider(aseco) is not None


async def _open_ultimania_window(aseco, login):
    service = provider(aseco)
    player = aseco.server.players.get_player(login)
    if service is not None and player is not None:
        await service.show(aseco, player)


async def _draw_ultimania_player(aseco, login):
    from apps.ui.config import _state
    from apps.ui.widgets.common import _hide, _send
    from apps.ui.widgets.records_common import _build_record_widget
    from apps.ui.widgets.records_common import ML_DEDI, _dedi_close_to_you

    service = provider(aseco)
    cfg = _state.dedi.get(Gameinfo.STNT)
    if (service is None or not cfg or not cfg.enabled or _state.challenge_show_next
            or not _state.player_visible.get(login, True)):
        await _hide(aseco, login, ML_DEDI)
        return
    player = aseco.server.players.get_player(login)
    style = aseco.services.get('ui/uistyle')
    modern = style is not None and style.resolve(player).base == 1
    entries = _dedi_close_to_you(service.rows, login, cfg.entries, cfg.topcount,
                                getattr(player, 'nickname', login), include_no_record=not modern)
    online = {p.login for p in aseco.server.players.all()} if _state.mark_online else set()
    xml = _build_record_widget(aseco=aseco, ml_id=ML_DEDI, cfg=replace(cfg, title='Ultimania Records'),
        login=login, entries=entries, online=online, mode=Gameinfo.STNT, click_action=ACTION)
    if _state.player_dedi_digest.get(login) != str(hash(xml)):
        await _send(aseco, login, xml)
        _state.player_dedi_digest[login] = str(hash(xml))


async def show_window(aseco, player, rows):
    from .service import current_uid
    uid = current_uid(aseco)

    def valid(current_aseco, current_player):
        return provider(current_aseco) is not None and current_uid(current_aseco) == uid

    table = [[str(row['rank']), str(row['score']), row['nickname'], row['login']] for row in rows]
    if not table:
        table = [['-', '-', 'No Ultimania scores yet.', '']]
    player.msgs = [[1, 'Ultimania Records - Stunts', [1.35, .12, .2, .7, .33],
                    ['Icons128x128_1', 'Rankings'], valid]]
    player.msgs.extend([[['Rank', 'Points', 'Player', 'Login']] + table[i:i + 20] for i in range(0, len(table), 20)])
    await _send_multipage(aseco, player)
