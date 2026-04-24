from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from pathlib import Path
from xml.sax.saxutils import escape

logger = logging.getLogger(__name__)

from pyxaseco.helpers import format_time
from pyxaseco.models import Gameinfo

from ..config import _state, _effective_mode
from ..helpers import (
    _clip,
    _enrich_track_with_challenge_info,
    _enrich_track_with_tmx,
    _fmt_track_value,
    _no_screenshot_image,
)
from ..ui import append_window_start, append_window_end

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


ML_CHALLENGE = 91805
ML_WINDOW = 91800
ML_SUBWIN = 91801
ML_TOGGLE = 91802



async def _open_challenge_window(aseco: 'Aseco', login: str):
    from .common import _send
    xml = await _build_last_current_next_window(aseco)
    await _send(aseco, login, xml)


async def _draw_challenge_player(aseco: 'Aseco', login: str):
    from .common import _hide, _send

    if not _state.challenge.enabled:
        await _hide(aseco, login, ML_CHALLENGE)
        return

    st = _state.style
    cfg = _state.challenge

    if _state.challenge_show_next:
        # Score-state: show next track info.
        # name, author, env, mood, author/gold/silver/bronzetime.
        # Uses _state.next_challenge cached in _on_end_race.
        nxt = _state.next_challenge
        nxt_name = str(nxt.get('name', '-') or '-')
        nxt_author = str(nxt.get('author', '-') or '-')
        nxt_env = str(nxt.get('env', '') or '')
        nxt_mood = str(nxt.get('mood', '') or '')
        nxt_atime = str(nxt.get('authortime', '-') or '-')
        nxt_gold = str(nxt.get('goldtime', '-') or '-')
        nxt_silver = str(nxt.get('silvertime', '-') or '-')
        nxt_bronze = str(nxt.get('bronzetime', '-') or '-')

        icon_style = _state.challenge_next.icon_style
        icon_substyle = _state.challenge_next.icon_substyle
        title_text = _state.challenge_next.title or 'Next Track'

        # Score-state widget is taller (14.1) to fit times grid.
        # Width: use challenge_next.width from XML <score><width> if set, else inherit
        # the race-state width from <challenge_widget><width>.
        widget_h = 14.1
        _score_w = _state.challenge_next.width
        widget_w = _score_w if _score_w > 0.0 else cfg.width
        _score_x = _state.challenge_next.pos_x if _state.challenge_next.pos_x != 0.0 else cfg.pos_x
        _score_y = _state.challenge_next.pos_y if _state.challenge_next.pos_y != 0.0 else cfg.pos_y

        xml = (
            f'<manialink id="{ML_CHALLENGE}">'
            f'<frame posn="{_score_x:.4f} {_score_y:.4f} 0">'
            f'<format textsize="1" textcolor="{st.col_default}"/>'
            f'<quad posn="0 0 0.001" sizen="{widget_w:.4f} {widget_h:.4f}"'
            f' action="{ML_TOGGLE}"'
            f' style="{st.bg_style}" substyle="{st.bg_substyle}"/>'
            f'<quad posn="0.4 -0.36 0.002" sizen="{widget_w - 0.8:.4f} 2"'
            f' style="{st.title_style}" substyle="{st.title_sub}"/>'
            f'<quad posn="0.6 -0.15 0.004" sizen="2.5 2.5"'
            f' style="{escape(icon_style)}" substyle="{escape(icon_substyle)}"/>'
            f'<label posn="3.2 -0.55 0.004" sizen="10.2 0" textsize="1"'
            f' text="{escape(title_text)}"/>'
            # Track name
            f'<label posn="1.35 -3 0.11" sizen="{widget_w - 2:.4f} 2"'
            f' text="{escape(_clip(nxt_name, 80))}"/>'
            # Author + env row
            f'<frame posn="0.5 -6 0">'
            f'<label posn="0.85 1 0.11" sizen="{widget_w - 2:.4f} 2" scale="0.9"'
            f' text="by {escape(_clip(nxt_author, 80))}"/>'
            f'<quad posn="2.95 -0.62 0.11" sizen="2.5 2.5" halign="right"'
            f' style="Icons128x128_1" substyle="Advanced"/>'
            f'<label posn="3.3 -1.1 0.11" sizen="{widget_w - 4:.4f} 2" scale="0.9"'
            f' text="{escape(nxt_env)}"/>'
            f'</frame>'
            # Times grid
            f'<frame posn="0.5 -10.3 0">'
            f'<quad posn="2.75 1.25 0.11" sizen="2 2" halign="right"'
            f' style="BgRaceScore2" substyle="ScoreReplay"/>'
            f'<label posn="3.3 1 0.11" sizen="6 2" scale="0.9"'
            f' text="{escape(nxt_atime)}"/>'
            f'<quad posn="2.75 -0.9 0.11" sizen="1.9 1.9" halign="right"'
            f' style="MedalsBig" substyle="MedalGold"/>'
            f'<label posn="3.3 -1.1 0.11" sizen="6 2" scale="0.9"'
            f' text="{escape(nxt_gold)}"/>'
            f'<quad posn="10.75 1.1 0.11" sizen="1.9 1.9" halign="right"'
            f' style="MedalsBig" substyle="MedalSilver"/>'
            f'<label posn="11.3 1 0.11" sizen="6 2" scale="0.9"'
            f' text="{escape(nxt_silver)}"/>'
            f'<quad posn="10.75 -0.9 0.11" sizen="1.9 1.9" halign="right"'
            f' style="MedalsBig" substyle="MedalBronze"/>'
            f'<label posn="11.3 -1.1 0.11" sizen="6 2" scale="0.9"'
            f' text="{escape(nxt_bronze)}"/>'
            f'</frame>'
            f'</frame></manialink>'
        )
    else:
        # Race-state: show current track info.
        cur = getattr(aseco.server, 'challenge', None)
        mode = _effective_mode(aseco)
        cur_data = _challenge_dict_from_obj(cur, mode)
        await _enrich_track_with_challenge_info(aseco, cur_data, mode, need_times=True)
        cur_name = str(cur_data.get('name', '') or '')
        cur_author = str(cur_data.get('author', '') or '')
        cur_atime = str(cur_data.get('authortime', '?') or '?')

        side = 'right' if cfg.pos_x < 0 else 'left'
        w_off = cfg.width - 15.5
        if side == 'right':
            icon_x = 12.5 + w_off
            title_x = 12.4 + w_off
            halign = 'right'
        else:
            icon_x = 0.6
            title_x = 3.2
            halign = 'left'

        xml = (
            f'<manialink id="{ML_CHALLENGE}">'
            f'<frame posn="{cfg.pos_x:.4f} {cfg.pos_y:.4f} 0">'
            f'<format textsize="1" textcolor="{st.col_default}"/>'
            f'<quad posn="0 0 0.01" sizen="{cfg.width:.4f} 8.65"'
            f' action="{ML_TOGGLE}"'
            f' style="{st.bg_style}" substyle="{st.bg_substyle}"/>'
            f'<quad posn="0.4 -0.36 0.02"'
            f' sizen="{cfg.width - 0.8:.4f} 2"'
            f' style="{st.title_style}" substyle="{st.title_sub}"/>'
            f'<quad posn="{icon_x:.4f} 0 0.04"'
            f' sizen="2.5 2.5"'
            f' style="{cfg.icon_style}" substyle="{cfg.icon_substyle}"/>'
            f'<label posn="{title_x:.4f} -0.55 0.04"'
            f' sizen="10.2 0" halign="{halign}" textsize="1"'
            f' text="{cfg.title}"/>'
            f'<label posn="1 -2.7 0.04" sizen="13.55 2" scale="1"'
            f' text="{_clip(cur_name, 80)}"/>'
            f'<label posn="1 -4.5 0.04" sizen="14.85 2" scale="0.9"'
            f' text="by {_clip(cur_author, 80)}"/>'
            f'<quad posn="0.7 -6.25 0.04" sizen="1.7 1.7"'
            f' style="BgRaceScore2" substyle="ScoreReplay"/>'
            f'<label posn="2.7 -6.55 0.04" sizen="6 2" scale="0.75"'
            f' text="{cur_atime}"/>'
            f'</frame></manialink>'
        )

    await _send(aseco, login, xml)



def _challenge_dict_from_obj(challenge, mode: int) -> dict:
    if not challenge:
        return {
            'uid': '',
            'name': '-',
            'author': '-',
            'authortime': '-',
            'goldtime': '-',
            'silvertime': '-',
            'bronzetime': '-',
            'env': '',
            'mood': '',
            'type': '',
            'style': '',
            'diffic': '',
            'routes': '',
            'awards': '',
            'section': '',
            'imageurl': _no_screenshot_image(),
            'pageurl': '',
            'dloadurl': '',
            'replayurl': '',
        }

    return {
        'uid': getattr(challenge, 'uid', '') or '',
        'name': getattr(challenge, 'name', '-') or '-',
        'author': getattr(challenge, 'author', '-') or '-',
        'filename': getattr(challenge, 'filename', '') or '',
        'authortime': _fmt_track_value(mode, getattr(challenge, 'authortime', 0)),
        'goldtime': _fmt_track_value(mode, getattr(challenge, 'goldtime', 0)),
        'silvertime': _fmt_track_value(mode, getattr(challenge, 'silvertime', 0)),
        'bronzetime': _fmt_track_value(mode, getattr(challenge, 'bronzetime', 0)),
        'authortime_ms': int(getattr(challenge, 'authortime', 0) or 0),
        'goldtime_ms': int(getattr(challenge, 'goldtime', 0) or 0),
        'silvertime_ms': int(getattr(challenge, 'silvertime', 0) or 0),
        'bronzetime_ms': int(getattr(challenge, 'bronzetime', 0) or 0),
        'env': getattr(challenge, 'environment', '') or getattr(challenge, 'environnement', '') or '',
        'mood': '',
        'type': '',
        'style': '',
        'diffic': '',
        'routes': '',
        'awards': '',
        'section': '',
        'imageurl': _no_screenshot_image(),
        'pageurl': '',
        'dloadurl': '',
        'replayurl': '',
    }


async def _get_next_track_info(aseco: 'Aseco', mode: int) -> dict:
    """
    Prefer jukebox first, then dedicated next challenge info if available.
    """
    try:
        from pyxaseco.plugins.plugin_rasp_jukebox import get_jukebox
        jb = get_jukebox()
        if isinstance(jb, dict) and jb:
            _uid, item = next(iter(jb.items()))
            data = {
                'name': item.get('Name') or item.get('FileName') or '-',
                'author': item.get('Author') or '-',
                'uid': item.get('uid', '') or '',
                'filename': item.get('FileName', '') or '',
                'authortime': '-',
                'goldtime': '-',
                'silvertime': '-',
                'bronzetime': '-',
                'authortime_ms': 0,
                'goldtime_ms': 0,
                'silvertime_ms': 0,
                'bronzetime_ms': 0,
                'env': item.get('Env') or item.get('Environment') or '',
                'mood': '',
                'type': '',
                'style': '',
                'diffic': '',
                'routes': '',
                'awards': '',
                'section': '',
                'imageurl': _no_screenshot_image(),
                'pageurl': '',
                'dloadurl': '',
                'replayurl': '',
            }
            await _enrich_track_with_challenge_info(aseco, data, mode, need_times=True, need_env=True)
            await _enrich_track_with_tmx(aseco, data, mode, need_times=False, need_env=True, need_mood=True, need_meta=True)
            return data
    except Exception:
        pass

    try:
        info = await aseco.client.query('GetNextChallengeInfo')
        if isinstance(info, dict):
            data = {
                'name': info.get('Name') or '-',
                'author': info.get('Author') or '-',
                'uid': info.get('UId', '') or info.get('Uid', '') or '',
                'filename': info.get('FileName', '') or '',
                'authortime': _fmt_track_value(mode, info.get('AuthorTime', 0)),
                'goldtime': _fmt_track_value(mode, info.get('GoldTime', 0)),
                'silvertime': _fmt_track_value(mode, info.get('SilverTime', 0)),
                'bronzetime': _fmt_track_value(mode, info.get('BronzeTime', 0)),
                'authortime_ms': int(info.get('AuthorTime', 0) or 0),
                'goldtime_ms': int(info.get('GoldTime', 0) or 0),
                'silvertime_ms': int(info.get('SilverTime', 0) or 0),
                'bronzetime_ms': int(info.get('BronzeTime', 0) or 0),
                'env': info.get('Environnement') or info.get('Environment') or '',
                'mood': '',
                'type': '',
                'style': '',
                'diffic': '',
                'routes': '',
                'awards': '',
                'section': '',
                'imageurl': _no_screenshot_image(),
                'pageurl': '',
                'dloadurl': '',
                'replayurl': '',
            }
            await _enrich_track_with_challenge_info(aseco, data, mode, need_times=True, need_env=True)
            await _enrich_track_with_tmx(aseco, data, mode, need_times=False, need_env=True, need_mood=True, need_meta=True)
            return data
    except Exception:
        pass

    return {
        'uid': '',
        'name': '-',
        'author': '-',
        'filename': '',
        'authortime': '-',
        'goldtime': '-',
        'silvertime': '-',
        'bronzetime': '-',
        'authortime_ms': 0,
        'goldtime_ms': 0,
        'silvertime_ms': 0,
        'bronzetime_ms': 0,
        'env': '',
        'mood': '',
        'type': '',
        'style': '',
        'diffic': '',
        'routes': '',
        'awards': '',
        'section': '',
        'imageurl': _no_screenshot_image(),
        'pageurl': '',
        'dloadurl': '',
        'replayurl': '',
    }


def _track_panel(x_off: float, panel_title: str, data: dict, icon_style: str, icon_substyle: str) -> str:
    raw_name = str(data.get('name', '-') or '-')
    raw_author = str(data.get('author', '-') or '-')

    name = _clip(raw_name, 80)
    author = _clip(raw_author, 80)

    authortime = str(data.get('authortime', '-') or '-')
    goldtime = str(data.get('goldtime', '-') or '-')
    silvertime = str(data.get('silvertime', '-') or '-')
    bronzetime = str(data.get('bronzetime', '-') or '-')
    env = str(data.get('env', '') or '')
    mood = str(data.get('mood', '') or '')
    ttype = str(data.get('type', '') or '')
    style = str(data.get('style', '') or '')
    diffic = str(data.get('diffic', '') or '')
    routes = str(data.get('routes', '') or '')
    awards = str(data.get('awards', '') or '')
    section = str(data.get('section', '') or '')
    imageurl = escape(str(data.get('imageurl', '') or ''))
    pageurl = escape(str(data.get('pageurl', '') or ''))
    dloadurl = escape(str(data.get('dloadurl', '') or ''))
    replayurl = escape(str(data.get('replayurl', '') or ''))

    xml = f'<frame posn="{x_off:.2f} 0 1">'
    xml += '<format textsize="1" textcolor="FFFF"/>'
    xml += '<quad posn="0 0 0.02" sizen="24.05 47" style="BgsPlayerCard" substyle="BgRacePlayerName"/>'
    xml += '<quad posn="0.4 -0.36 0.04" sizen="23.25 2" style="BgsPlayerCard" substyle="ProgressBar"/>'
    xml += f'<quad posn="0.6 0 0.05" sizen="2.5 2.5" style="{escape(icon_style)}" substyle="{escape(icon_substyle)}"/>'
    xml += f'<label posn="3.2 -0.55 0.05" sizen="23.6 0" textsize="1" text="{escape(panel_title)}"/>'

    xml += '<quad posn="1.4 -3.6 0.03" sizen="21.45 16.29" bgcolor="FFF9"/>'
    xml += '<label posn="12.1 -11 0.04" sizen="20 2" halign="center" textsize="1" text="Press DEL if can not see an Image here!"/>'
    xml += f'<quad posn="1.5 -3.7 0.50" sizen="21.25 16.09" image="{imageurl}"/>'

    xml += f'<label posn="1.4 -21 0.02" sizen="21 3" textsize="2" text="$S{name}"/>'
    xml += f'<label posn="1.4 -23.3 0.02" sizen="21 3" textsize="1" text="by {author}"/>'

    xml += '<frame posn="3.2 -33 0">'
    xml += f'<format textsize="1" textcolor="{_state.style.col_default}"/>'
    xml += '<quad posn="0.1 7.2 0.1" sizen="2.2 2.2" halign="right" style="BgRaceScore2" substyle="ScoreReplay"/>'
    xml += '<quad posn="0 4.8 0.1" sizen="2 2" halign="right" style="MedalsBig" substyle="MedalGold"/>'
    xml += '<quad posn="0 2.5 0.1" sizen="2 2" halign="right" style="MedalsBig" substyle="MedalSilver"/>'
    xml += '<quad posn="0 0.2 0.1" sizen="2 2" halign="right" style="MedalsBig" substyle="MedalBronze"/>'
    xml += '<quad posn="0.2 -1.8 0.1" sizen="2.6 2.6" halign="right" style="Icons128x128_1" substyle="Advanced"/>'
    xml += '<quad posn="0.2 -4.1 0.1" sizen="2.6 2.6" halign="right" style="Icons128x128_1" substyle="Manialink"/>'
    xml += f'<label posn="0.5 6.9 0.1" sizen="8 2" text="{escape(authortime)}"/>'
    xml += f'<label posn="0.5 4.6 0.1" sizen="8 2" text="{escape(goldtime)}"/>'
    xml += f'<label posn="0.5 2.3 0.1" sizen="8 2" text="{escape(silvertime)}"/>'
    xml += f'<label posn="0.5 0 0.1" sizen="8 2" text="{escape(bronzetime)}"/>'
    xml += f'<label posn="0.5 -2.3 0.1" sizen="8 2" text="{escape(env)}"/>'
    xml += f'<label posn="0.5 -4.6 0.1" sizen="8 2" text="{escape(mood)}"/>'
    xml += '</frame>'

    if pageurl:
        xml += '<frame posn="10.6 -33 0">'
        xml += f'<format textsize="1" textcolor="{_state.style.col_default}"/>'
        xml += '<label posn="0 6.9 0.1" sizen="5 2.2" text="Type:"/>'
        xml += '<label posn="0 4.6 0.1" sizen="5 2" text="Style:"/>'
        xml += '<label posn="0 2.3 0.1" sizen="5 2" text="Difficult:"/>'
        xml += '<label posn="0 0 0.1" sizen="5 2" text="Routes:"/>'
        xml += '<label posn="0 -2.3 0.1" sizen="5 2.6" text="Awards:"/>'
        xml += '<label posn="0 -4.6 0.1" sizen="5 2.6" text="Section:"/>'
        xml += f'<label posn="5.1 6.9 0.1" sizen="10.5 2" text=" {escape(ttype)}"/>'
        xml += f'<label posn="5.1 4.6 0.1" sizen="10.5 2" text=" {escape(style)}"/>'
        xml += f'<label posn="5.1 2.3 0.1" sizen="10.5 2" text=" {escape(diffic)}"/>'
        xml += f'<label posn="5.1 0 0.1" sizen="10.5 2" text=" {escape(routes)}"/>'
        xml += f'<label posn="5.1 -2.3 0.1" sizen="10.5 2" text=" {escape(awards)}"/>'
        xml += f'<label posn="5.1 -4.6 0.1" sizen="10.5 2" text=" {escape(section)}"/>'
        xml += '</frame>'

        xml += '<frame posn="1.6 -40.5 0">'
        xml += '<format textsize="1" style="TextCardScores2"/>'
        if pageurl:
            xml += f'<label posn="0 -0.3 0.04" sizen="24 2" scale="0.5" text="$FFF&#0187; Visit Track Page" url="{pageurl}"/>'
        if dloadurl:
            xml += f'<label posn="0 -2.2 0.04" sizen="24 2" scale="0.5" text="$FFF&#0187; Download Track" url="{dloadurl}"/>'
        if replayurl:
            xml += f'<label posn="0 -4.1 0.04" sizen="24 2" scale="0.5" text="$FFF&#0187; Download Replay" url="{replayurl}"/>'
        xml += '</frame>'

    xml += '</frame>'
    return xml


async def _last_track_from_history(aseco: 'Aseco') -> dict:
    mode = _effective_mode(aseco)

    try:
        hist_path = Path(getattr(aseco, '_base_dir', '.')) / 'trackhist.txt'
        if not hist_path.exists():
            return {}

        lines = [
            line.strip()
            for line in hist_path.read_text(encoding='utf-8', errors='ignore').splitlines()
            if line.strip()
        ]
        if len(lines) < 2:
            return {}

        cur_uid = (getattr(getattr(aseco.server, 'challenge', None), 'uid', '') or '').strip()

        prev_uid = ''
        for uid in reversed(lines[:-1]):
            uid = uid.strip()
            if uid and uid != cur_uid:
                prev_uid = uid
                break

        if not prev_uid:
            return {}

        result = {
            'uid': prev_uid,
            'name': '-',
            'author': '-',
            'filename': '',
            'authortime': '-',
            'goldtime': '-',
            'silvertime': '-',
            'bronzetime': '-',
            'authortime_ms': 0,
            'goldtime_ms': 0,
            'silvertime_ms': 0,
            'bronzetime_ms': 0,
            'env': '',
            'mood': '',
            'type': '',
            'style': '',
            'diffic': '',
            'routes': '',
            'awards': '',
            'section': '',
            'imageurl': _no_screenshot_image(),
            'pageurl': '',
            'dloadurl': '',
            'replayurl': '',
        }

        try:
            from pyxaseco.plugins.plugin_localdatabase import get_pool
            pool = await get_pool()
        except Exception:
            pool = None

        if pool:
            try:
                async with pool.acquire() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            'SELECT Name, Author, Environment FROM challenges WHERE Uid=%s LIMIT 1',
                            (prev_uid,)
                        )
                        row = await cur.fetchone()
                        if row:
                            result['name'] = row[0] or '-'
                            result['author'] = row[1] or '-'
                            result['env'] = row[2] or ''
            except Exception:
                pass

        try:
            tmx_times = await _get_tmx_trackinfo_for_uid(aseco, prev_uid, mode)
            if tmx_times:
                result.update({k: v for k, v in tmx_times.items() if v not in ('', None)})
        except Exception as e:
            logger.debug('[Eyepiece/Challenge] previous track TMX times failed for uid=%s: %r', prev_uid, e)

        try:
            tracks = await aseco.client.query('GetChallengeList', 5000, 0) or []
            for t in tracks:
                tuid = (t.get('UId', '') or t.get('Uid', '') or '').strip()
                if tuid == prev_uid:
                    result['name'] = t.get('Name', result['name']) or result['name']
                    result['author'] = t.get('Author', result['author']) or result['author']
                    result['filename'] = t.get('FileName', result['filename']) or result['filename']

                    at = int(t.get('AuthorTime', 0) or 0)
                    gt = int(t.get('GoldTime', 0) or 0)
                    st = int(t.get('SilverTime', 0) or 0)
                    bt = int(t.get('BronzeTime', 0) or 0)

                    if at > 0:
                        result['authortime_ms'] = at
                        result['authortime'] = _fmt_track_value(mode, at)
                    if gt > 0:
                        result['goldtime_ms'] = gt
                        result['goldtime'] = _fmt_track_value(mode, gt)
                    if st > 0:
                        result['silvertime_ms'] = st
                        result['silvertime'] = _fmt_track_value(mode, st)
                    if bt > 0:
                        result['bronzetime_ms'] = bt
                        result['bronzetime'] = _fmt_track_value(mode, bt)

                    result['env'] = t.get('Environnement', '') or t.get('Environment', '') or result['env']
                    break
        except Exception:
            pass

        return result

    except Exception:
        return {}

async def _build_last_current_next_window(aseco: 'Aseco') -> str:
    cur = getattr(aseco.server, 'challenge', None)
    mode = _effective_mode(aseco)

    current_data = _challenge_dict_from_obj(cur, mode)
    last_data = await _last_track_from_history(aseco)
    if not last_data:
        last_data = {
            'uid': '',
            'name': '-',
            'author': '-',
            'authortime': '-',
            'goldtime': '-',
            'silvertime': '-',
            'bronzetime': '-',
            'env': '',
            'mood': '',
            'type': '',
            'style': '',
            'diffic': '',
            'routes': '',
            'awards': '',
            'section': '',
            'imageurl': _no_screenshot_image(),
            'pageurl': '',
            'dloadurl': '',
            'replayurl': '',
        }

    next_data = await _get_next_track_info(aseco, mode)

    await _enrich_track_with_challenge_info(aseco, current_data, mode, need_times=True, need_env=True)
    await _enrich_track_with_challenge_info(aseco, last_data, mode, need_times=True, need_env=True)
    await _enrich_track_with_challenge_info(aseco, next_data, mode, need_times=True, need_env=True)

    logger.debug(
        '[Eyepiece/Challenge] panel UIDs last=%s current=%s next=%s',
        last_data.get('uid', ''),
        current_data.get('uid', ''),
        next_data.get('uid', ''),
    )

    try:
        await _enrich_track_with_tmx(aseco, current_data, mode, need_times=True, need_env=True, need_mood=True, need_meta=True)
    except Exception as e:
        logger.debug('[Eyepiece/Challenge] current track TMX info failed: %r', e)
    
    try:
        await _enrich_track_with_tmx(aseco, last_data, mode, need_times=True, need_env=True, need_mood=True, need_meta=True)
    except Exception as e:
        logger.debug('[Eyepiece/Challenge] last track TMX info failed: %r', e)
    
    try:
        await _enrich_track_with_tmx(aseco, next_data, mode, need_times=True, need_env=True, need_mood=True, need_meta=True)
    except Exception as e:
        logger.debug('[Eyepiece/Challenge] next track TMX info failed: %r', e)

    logger.debug('[Eyepiece/Challenge] last_data=%r', last_data)
    logger.debug('[Eyepiece/Challenge] current_data=%r', current_data)
    logger.debug('[Eyepiece/Challenge] next_data=%r', next_data)

    p = []
    append_window_start(
        p,
        ml_window=ML_WINDOW,
        ml_subwin=ML_SUBWIN,
        title='Track overview',
        icon_style='Icons128x128_1',
        icon_substyle='Browse',
        content_frame_pos='2.5 -5.7 0.05',
    )
    p.append(_track_panel(
        0.00,
        _state.challenge_last.title or 'Last Track',
        last_data,
        _state.challenge_last.icon_style,
        _state.challenge_last.icon_substyle,
    ))
    p.append(_track_panel(
        25.45,
        _state.challenge_current.title or 'Current Track',
        current_data,
        _state.challenge_current.icon_style,
        _state.challenge_current.icon_substyle,
    ))
    p.append(_track_panel(
        50.85,
        _state.challenge_next.title or 'Next Track',
        next_data,
        _state.challenge_next.icon_style,
        _state.challenge_next.icon_substyle,
    ))
    append_window_end(p)
    return ''.join(p)
