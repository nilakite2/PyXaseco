from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from pyxaseco.helpers import display_manialink

from ..config import WidgetCfg, _load_config, _state

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


_WIDGET_IDS = (91811, 91812, 91813, 91832, 91834)
_BAR_WIDGET_IDS = (
    91809, 91807, 91808, 91837, 91838,
    91844, 91849, 91810, 91835,
    91841, 91836, 91833,
    5834287, 5834288,
)
_MANIA_KARMA_IDS = (91101, 91102, 91103, 91104, 91105, 91106, 91107)


async def chat_togglewidgets(aseco: 'Aseco', command: dict):
    from ..widgets.common import _send_chat, _hide
    from .events import _redraw_player

    player = command['author']
    login = player.login
    visible = not _state.player_visible.get(login, True)
    _state.player_visible[login] = visible

    if visible:
        _state.player_local_digest.pop(login, None)
        _state.player_dedi_digest.pop(login, None)
        _state.player_live_digest.pop(login, None)
        await _send_chat(aseco, login, '{#server}>> Your record widgets are now shown.')
        await _redraw_player(aseco, login)

        # Restore non-clock Eyepiece HUD bars for this player. These widgets are
        # broadcast by the bar module, so immediately re-hide them again for any
        # players who still have widgets disabled.
        try:
            from ..widgets.bar_widgets import draw_all_score_bars, draw_all_race_bars

            if _state.challenge_show_next:
                await draw_all_score_bars(aseco)
            else:
                await draw_all_race_bars(aseco)

            for other in aseco.server.players.all():
                other_login = other.login
                if other_login == login or _state.player_visible.get(other_login, True):
                    continue
                for ml_id in _BAR_WIDGET_IDS:
                    await _hide(aseco, other_login, ml_id)
        except Exception:
            pass

        # Restore ManiaKarma only for this player.
        try:
            mania_karma = (
                sys.modules.get('pyxaseco_plugins.plugin_mania_karma')
                or sys.modules.get('pyxaseco.plugins.plugin_mania_karma')
            )
            if mania_karma is None:
                try:
                    import pyxaseco_plugins.plugin_mania_karma as mania_karma  # type: ignore
                except Exception:
                    import pyxaseco.plugins.plugin_mania_karma as mania_karma  # type: ignore

            if mania_karma._cfg.gm_cfg(mania_karma._cfg.current_state).enabled:
                widgets = ['skeleton_score', 'cups_values'] if mania_karma._cfg.current_state == 7 else ['skeleton_race', 'cups_values']
                await mania_karma._send_widget_combination(aseco, widgets, player)
                await mania_karma._send_widget_combination(aseco, ['player_marker'], player)
                await mania_karma._send_connection_status(
                    aseco,
                    getattr(mania_karma, '_retrytime', 0) == 0,
                    mania_karma._cfg.current_state,
                )
        except Exception:
            pass
    else:
        for ml_id in _WIDGET_IDS:
            await _hide(aseco, login, ml_id)
        for ml_id in _BAR_WIDGET_IDS:
            await _hide(aseco, login, ml_id)
        for ml_id in _MANIA_KARMA_IDS:
            await _hide(aseco, login, ml_id)
        await _send_chat(aseco, login, '{#server}>> Your record widgets are now hidden.')


async def chat_eyepiece(aseco: 'Aseco', command: dict):
    from ..utils import _mode_name

    player = command['author']
    login = player.login
    mode = getattr(aseco.server.gameinfo, 'mode', -1)

    def ena(cfg_dict):
        cfg = cfg_dict.get(mode, WidgetCfg())
        return 'enabled' if cfg.enabled else 'disabled'

    rows = [
        ['Core port',      '{#black}Eyepiece 1.0-Alpha'],
        ['Mode',           '{#black}' + _mode_name(mode)],
        ['Challenge',      '{#black}' + ('enabled' if _state.challenge.enabled else 'disabled')],
        ['Local records',  '{#black}' + ena(_state.local)],
        ['Dedimania recs', '{#black}' + ena(_state.dedi)],
        ['Live rankings',  '{#black}' + ena(_state.live)],
        ['CP count',       '{#black}' + ('enabled' if _state.cp.enabled else 'disabled')],
        [],
        ['/togglewidgets', '{#black}Hide/show all Eyepiece widgets'],
        ['/eyepiece',      '{#black}Show this summary'],
        ['/elist',         '{#black}Track-list window'],
        ['/estat',         '{#black}Stats/records windows'],
        ['/eyeset',        '{#black}Admin: adjust Eyepiece settings (MasterAdmin only)'],
    ]
    display_manialink(
        aseco,
        login,
        'Records-Eyepiece 1.0-Alpha',
        ['Icons64x64_1', 'TrackInfo', -0.01],
        rows,
        [1.15, 0.32, 0.83],
        'OK',
    )


async def _elist_redirect(aseco: 'Aseco', command: dict):
    from ..tracklist import _send_tracklist_window, _send_trackauthorlist_window

    player = command['author']
    param = (command.get('params') or '').strip().upper()

    filter_map = {
        'JUKEBOX':    'JUKEBOX',
        'NORECENT':   'NORECENT',
        'ONLYRECENT': 'ONLYRECENT',
        'NORANK':     'NORANK',
        'ONLYRANK':   'ONLYRANK',
        'NOFINISH':   'NOFINISH',
        'NOAUTHOR':   'NOAUTHOR',
        'NOGOLD':     'NOGOLD',
        'NOSILVER':   'NOSILVER',
        'NOBRONZE':   'NOBRONZE',
        'STADIUM':    'STADIUM',
        'BAY':        'BAY',
        'COAST':      'COAST',
        'DESERT':     'DESERT',
        'SPEED':      'DESERT',
        'ISLAND':     'ISLAND',
        'RALLY':      'RALLY',
        'ALPINE':     'ALPINE',
        'SNOW':       'ALPINE',
        'SUNRISE':    'SUNRISE',
        'DAY':        'DAY',
        'SUNSET':     'SUNSET',
        'NIGHT':      'NIGHT',
        'MULTILAP':   'MULTILAP',
        'NOMULTILAP': 'NOMULTILAP',
        'BEST':       'BEST',
        'WORST':      'WORST',
        'SHORTEST':   'SHORTEST',
        'LONGEST':    'LONGEST',
        'NEWEST':     'NEWEST',
        'OLDEST':     'OLDEST',
        'TRACK':      'TRACK',
        'SORTAUTHOR': 'SORTAUTHOR',
        'BESTKARMA':  'BESTKARMA',
        'WORSTKARMA': 'WORSTKARMA',
    }

    if not param:
        await _send_tracklist_window(aseco, player, page=0)
    elif param == 'AUTHOR':
        await _send_trackauthorlist_window(aseco, player, page=0)
    elif param in filter_map:
        await _send_tracklist_window(aseco, player, page=0, filter_cmd=filter_map[param])
    else:
        await _send_tracklist_window(
            aseco,
            player,
            page=0,
            search=command.get('params', '').strip(),
        )


async def chat_eyeset(aseco: 'Aseco', command: dict) -> None:
    from ..utils import _loop_time
    from ..widgets.common import _send_chat
    from .events import (
        _on_new_challenge,
        _on_new_challenge2,
        _apply_custom_ui_all,
        _redraw_all,
        _draw_local_all,
        _draw_dedi_all,
    )

    player = command['author']
    login = player.login

    if not aseco.is_master_admin(player):
        await _send_chat(aseco, login, '{#server}> {#error}You need MasterAdmin rights for /eyeset.')
        return

    params = (command.get('params') or '').strip()
    p_up = params.upper()

    if p_up == 'RELOAD':
        aseco.console('[Records-Eyepiece] MasterAdmin %s reloads the configuration.', login)

        _state.player_local_digest.clear()
        _state.player_dedi_digest.clear()
        _state.player_live_digest.clear()

        _load_config(aseco)

        await _on_new_challenge(aseco, aseco.server.challenge)
        await _on_new_challenge2(aseco, aseco.server.challenge)
        await _apply_custom_ui_all(aseco)
        await _redraw_all(aseco)
        await _send_chat(aseco, login, '{#server}>> Reload of records_eyepiece.xml done.')
        return

    if p_up.startswith('LFRESH '):
        try:
            val = max(1, int(params.split()[1]))
        except (IndexError, ValueError):
            await _send_chat(aseco, login, '{#server}> {#error}Usage: /eyeset lfresh <seconds>')
            return

        old = _state.refresh_interval
        _state.refresh_interval = val
        _state.next_refresh = _loop_time() + val
        await _send_chat(aseco, login, f'{{#server}}>> Set refresh_interval from {old}s to {val}s.')
        return

    if p_up.startswith('PLAYERMARKER '):
        arg = params.split()[1].upper() if len(params.split()) > 1 else ''
        if arg not in ('TRUE', 'FALSE'):
            await _send_chat(aseco, login, '{#server}> {#error}Usage: /eyeset playermarker true|false')
            return

        _state.mark_online = (arg == 'TRUE')
        _state.player_local_digest.clear()
        _state.player_dedi_digest.clear()
        await _draw_local_all(aseco)
        await _draw_dedi_all(aseco)
        await _send_chat(aseco, login, f'{{#server}}>> Set playermarker to {arg.lower()}.')
        return

    rows = [
        ['$s/eyeset sub-commands:', ''],
        ['reload', 'Reload records_eyepiece.xml and redraw all widgets'],
        ['lfresh <N>', 'Set live-refresh interval to N seconds'],
        ['playermarker true|false', 'Toggle online-player markers in record widgets'],
    ]
    display_manialink(
        aseco,
        login,
        'Records-Eyepiece /eyeset',
        ['Icons64x64_1', 'TrackInfo', -0.01],
        rows,
        [1.15, 0.32, 0.83],
        'OK',
    )


async def chat_estat(aseco: 'Aseco', command: dict) -> None:
    from ..widgets.records_local import _build_local_records_window
    from ..widgets.records_dedi import _build_dedi_records_window
    from ..toplists import _build_generic_toplist_window
    from ..widgets.common import _send, _send_chat

    player = command['author']
    login = player.login
    params = (command.get('params') or '').strip().upper()

    if params == 'LOCALRECS':
        xml = await _build_local_records_window(aseco, 0)
        if xml:
            await _send(aseco, login, xml)
        else:
            await _send_chat(aseco, login, '{#server}> No local records to display.')
        return

    if params == 'DEDIRECS':
        xml = _build_dedi_records_window(aseco, 0)
        if xml:
            await _send(aseco, login, xml)
        else:
            await _send_chat(aseco, login, '{#server}> No Dedimania records to display.')
        return

    if getattr(aseco.server, 'gamestate', None) not in (None, 3) and getattr(aseco.server, 'gamestate', None) != getattr(getattr(aseco.server, '__class__', object), 'RACE', 3):
        await _send_chat(aseco, login, '{#server}> This window is only available during race.')
        return

    if params in ('TOPRANKS', 'TOPWINNERS', 'MOSTRECORDS', 'TOPPLAYTIME', 'MOSTFINISHED', 'TOPACTIVE', 'TOPVOTERS', 'TOPVISITORS', 'TOPDONATORS'):
        xml = await _build_generic_toplist_window(aseco, params)
        if xml:
            await _send(aseco, login, xml)
        else:
            await _send_chat(aseco, login, '{#server}> No data to display.')
        return

    rows = [
        ['$s/estat <param> — opens a stats window:', ''],
        [],
        ['LOCALRECS',    'Scrollable list of all local records on this track'],
        ['DEDIRECS',     'Scrollable list of all Dedimania records on this track'],
        ['TOPRANKS',     'Top-ranked players (by total rank sum)'],
        ['TOPWINNERS',   'Players with most race wins on this server'],
        ['MOSTRECORDS',  'Players holding the most local records'],
        ['TOPPLAYTIME',  'Players with most playtime on this server'],
        ['MOSTFINISHED', 'Players who finished the most tracks'],
        ['TOPACTIVE',    'Most active players (recent visits)'],
        ['TOPVOTERS',    'Players who voted the most on karma'],
        ['TOPVISITORS',  'Players with the most recorded visits'],
        ['TOPDONATORS',  'Players with the most donations'],
    ]
    display_manialink(
        aseco,
        login,
        'Records-Eyepiece /estat',
        ['Icons64x64_1', 'TrackInfo', -0.01],
        rows,
        [1.15, 0.32, 0.83],
        'OK',
    )
