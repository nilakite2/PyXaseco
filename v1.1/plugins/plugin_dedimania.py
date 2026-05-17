"""
plugin_dedimania.py — Port of plugins/plugin.dedimania.php

Protocol: Every HTTP POST is a system.multicall that starts with
dedimania.Authenticate, followed by actual API call(s), then
dedimania.WarningsAndTTR.

Config: dedimania.xml next to plugins.xml
"""

from __future__ import annotations
import logging
import pathlib
import time
import xmlrpc.client
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco

logger = logging.getLogger(__name__)

DEDI_TIMEOUT  = 1800
DEDI_REFRESH  = 240
DEDI_MIN_AUTH = 8000
DEDI_MIN_TIME = 6000

dedi_db: dict   = {}
_connected      = False
_bad_time: float = 0.0
_last_sent: float = 0.0


def register(aseco: 'Aseco'):
    aseco.register_event('onSync',             _dedi_init)
    aseco.register_event('onEverySecond',      _dedi_update)
    aseco.register_event('onPlayerConnect',    _dedi_playerconnect)
    aseco.register_event('onPlayerDisconnect', _dedi_playerdisconnect)
    aseco.register_event('onNewChallenge',     _dedi_newchallenge)
    aseco.register_event('onEndRace',          _dedi_endrace)
    aseco.register_event('onPlayerFinish',     _dedi_playerfinish)


# ---------------------------------------------------------------------------
# Multicall helpers
# ---------------------------------------------------------------------------

def _auth_struct() -> dict:
    return {
        'Game':        'TMF',
        'Login':       dedi_db.get('Login', ''),
        'Password':    dedi_db.get('Password', ''),
        'Tool':        'PYXASECO',
        'Version':     '1.0',
        'Nation':      dedi_db.get('Nation', ''),
        'Packmask':    dedi_db.get('Packmask', ''),
        'PlayersGame': True,
    }


def _build_multicall(*calls) -> bytes:
    """Build system.multicall payload with auth prefix and TTR suffix."""
    methods = [{'methodName': 'dedimania.Authenticate', 'params': [_auth_struct()]}]
    for methodName, *args in calls:
        methods.append({'methodName': methodName, 'params': list(args)})
    methods.append({'methodName': 'dedimania.WarningsAndTTR', 'params': []})
    return xmlrpc.client.dumps((methods,), 'system.multicall').encode('utf-8')


async def _dedi_post(payload: bytes, timeout: int = 15):
    try:
        import aiohttp
        url = dedi_db.get('Url', 'http://dedimania.net:8002/Dedimania')
        async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=timeout)) as sess:
            async with sess.post(url, data=payload,
                                 headers={'Content-Type': 'text/xml'}) as resp:
                body = await resp.text(errors='replace')
        results, _ = xmlrpc.client.loads(body)
        if results and isinstance(results[0], list):
            return results[0]
        return results
    except Exception as e:
        logger.debug('[Dedimania] POST error: %s', e)
        return None


def _extract(results, index: int):
    """results[0]=Auth, results[1+index]=our call, results[-1]=TTR."""
    idx = index + 1
    if results and len(results) > idx:
        r = results[idx]
        if isinstance(r, list) and len(r) == 1:
            return r[0]
        return r
    return None


# ---------------------------------------------------------------------------
# Init / connect
# ---------------------------------------------------------------------------

async def _dedi_init(aseco: 'Aseco', _data):
    global dedi_db, _connected, _bad_time, _last_sent

    try:
        from pyxaseco.core.config import parse_xml_file
        base = pathlib.Path(getattr(aseco, '_base_dir', '.'))
        cfg_path = base / 'dedimania.xml'
        if not cfg_path.exists():
            aseco.console('[Dedimania] Config not found: {1}', str(cfg_path))
            return

        cfg = parse_xml_file(cfg_path)
        if not cfg:
            return

        root = cfg.get('DEDIMANIA', {})
        db   = root.get('DATABASE', [{}])[0]
        acc  = root.get('MASTERSERVER_ACCOUNT', [{}])[0]

        def g(blk, key, default=''):
            v = blk.get(key.upper(), [default])
            return v[0] if v else default

        def b(blk, key, default=False):
            return str(g(blk, key, 'false')).lower() == 'true'

        dedi_db = {
            'Url':            g(db, 'URL', 'http://dedimania.net:8002/Dedimania'),
            'Name':           g(db, 'NAME', 'Dedimania'),
            'Welcome':        g(db, 'WELCOME', ''),
            'TimeoutMsg':     g(db, 'TIMEOUT', ''),
            'LogNews':        b(db, 'LOG_NEWS'),
            'ShowWelcome':    b(db, 'SHOW_WELCOME', True),
            'ShowMinRecs':    int(g(db, 'SHOW_MIN_RECS', '8')),
            'ShowRecsBefore': int(g(db, 'SHOW_RECS_BEFORE', '1')),
            'ShowRecsAfter':  int(g(db, 'SHOW_RECS_AFTER', '1')),
            'ShowRecsRange':  b(db, 'SHOW_RECS_RANGE', True),
            'DisplayRecs':    b(db, 'DISPLAY_RECS', True),
            'RecsInWindow':   b(db, 'RECS_IN_WINDOW'),
            'ShowRecLogins':  b(db, 'SHOW_REC_LOGINS', True),
            'LimitRecs':      int(g(db, 'LIMIT_RECS', '10')),
            'MaxRank':        30,
            'ServerMaxRank':  30,
            'Login':          g(acc, 'LOGIN'),
            'Password':       g(acc, 'PASSWORD'),
            'Nation':         g(acc, 'NATION'),
            'Packmask':       aseco.server.packmask,
            'Messages':       root.get('MESSAGES', [{}])[0] if root.get('MESSAGES') else {},
            'RecsValid':      False,
            'TrackValid':     False,
            'BannedLogins':   [],
            'Challenge':      {},
            'Results':        {},
            'News':           [],
        }

        if not dedi_db['Login'] or dedi_db['Login'] in ('', 'YOUR_SERVER_LOGIN'):
            aseco.console('[Dedimania] Not configured — skipping.')
            return

        aseco.console('************* (Dedimania) *************')
        await _connect(aseco)
        aseco.console('------------- (Dedimania) -------------')
        _last_sent = time.time()

    except Exception as e:
        logger.warning('[Dedimania] Init error: %s', e)


async def _connect(aseco: 'Aseco'):
    global _connected, _bad_time

    aseco.console('* Dedimania: connecting to {1} ...', dedi_db.get('Url', ''))

    try:
        payload = _build_multicall(('dedimania.ValidateAccount',))
        results = await _dedi_post(payload)

        if not results:
            aseco.console('* Dedimania: no response from server')
            _bad_time = time.time()
            return

        auth = results[0]
        if isinstance(auth, list) and auth:
            auth = auth[0]

        validate = _extract(results, 0)

        if isinstance(validate, dict) and validate.get('Status'):
            _connected = True
            dedi_db['News'] = validate.get('Messages', []) or []
            aseco.console('* Dedimania: connection OK!')

            if dedi_db.get('LogNews'):
                for news in dedi_db['News']:
                    if isinstance(news, dict):
                        aseco.console(
                            '* NEWS ({1}, {2}): {3}',
                            dedi_db.get('Name', 'Dedimania'),
                            news.get('Date', ''),
                            news.get('Text', ''),
                        )
            return

        aseco.console(
            '* Dedimania: authentication failed: auth={1} validate={2}',
            str(auth)[:80],
            str(validate)[:150],
        )

    except Exception as e:
        aseco.console('* Dedimania: connection error: {1}', str(e))

    _bad_time = time.time()


# ---------------------------------------------------------------------------
# Periodic keep-alive
# ---------------------------------------------------------------------------

async def _dedi_update(aseco: 'Aseco', _param=None):
    global _last_sent, _connected, _bad_time
    if not dedi_db:
        return
    if _connected:
        if _last_sent + DEDI_REFRESH < time.time():
            await _announce(aseco)
    else:
        if _bad_time > 0 and (time.time() - _bad_time) > DEDI_TIMEOUT:
            if dedi_db.get('TimeoutMsg'):
                msg = dedi_db['TimeoutMsg'].replace('{1}', str(round(DEDI_TIMEOUT / 60)))
                await aseco.client.query_ignore_result('ChatSendServerMessage', aseco.format_colors('{#server}>> ' + msg))
            aseco.console('[Dedimania] Retry connection...')
            await _connect(aseco)


async def _announce(aseco: 'Aseco'):
    global _last_sent
    _last_sent = time.time()
    try:
        srv = await _server_info(aseco)
        pls = _collect_players(aseco)
        mode = getattr(aseco.server.gameinfo, 'mode', 1)
        payload = _build_multicall(
            ('dedimania.UpdateServerPlayers', 'TMF', mode, srv, pls),
        )
        await _dedi_post(payload, timeout=10)
    except Exception as e:
        logger.debug('[Dedimania] Announce error: %s', e)


# ---------------------------------------------------------------------------
# Player events
# ---------------------------------------------------------------------------

async def _dedi_playerconnect(aseco: 'Aseco', player):
    if _connected and not _is_server_login(aseco, player.login) and not _is_lan_login(player.login):
        try:
            payload = _build_multicall(
                ('dedimania.PlayerArrive',
                 'TMF',
                 player.login,
                 player.nickname,
                 getattr(player, 'nation', ''),
                 getattr(player, 'teamname', ''),
                 getattr(player, 'ladderrank', 0),
                 bool(getattr(player, 'isspectator', False)),
                 bool(getattr(player, 'isofficial', False))),
            )
            results = await _dedi_post(payload)
            data = _extract(results, 0)

            if isinstance(data, dict):
                if dedi_db.get('RecsValid'):
                    for rec in dedi_db.get('Challenge', {}).get('Records', []):
                        if isinstance(rec, dict) and rec.get('Login') == player.login:
                            rec['NickName'] = player.nickname
                            break

                player.dedirank = int(
                    data.get('MaxRank', dedi_db.get('ServerMaxRank', dedi_db.get('MaxRank', 30)))
                    or dedi_db.get('ServerMaxRank', dedi_db.get('MaxRank', 30))
                )

                status = int(data.get('Status', 0) or 0)
                if status % 2 == 1:
                    if player.login not in dedi_db['BannedLogins']:
                        dedi_db['BannedLogins'].append(player.login)

                    msg_tpl = dedi_db.get('Messages', {}).get(
                        'BANNED_LOGIN',
                        ['{#server}>> {#highlite}{1}{#dedimsg} ({2}) is banned on Dedimania - finishes ignored!']
                    )
                    msg = msg_tpl[0] if isinstance(msg_tpl, list) else str(msg_tpl)
                    msg = msg.replace('{1}', player.nickname).replace('{2}', player.login)
                    await aseco.client.query_ignore_result('ChatSendServerMessage', aseco.format_colors(msg))
                    aseco.console('[Dedimania] player {1} is banned - finishes ignored!', player.login)

        except Exception as e:
            logger.debug('[Dedimania] PlayerArrive error for %s: %s', player.login, e)

    if dedi_db.get('ShowWelcome') and dedi_db.get('Welcome'):
        msg = '{#server}> ' + dedi_db['Welcome']
        msg = msg.replace('{br}', '\n')
        msg = aseco.format_colors(msg)
        await aseco.client.query_ignore_result('ChatSendServerMessageToLogin', msg, player.login)


async def _dedi_playerdisconnect(aseco: 'Aseco', player):
    if _connected and not _is_server_login(aseco, player.login) and not _is_lan_login(player.login):
        try:
            payload = _build_multicall(
                ('dedimania.PlayerLeave', 'TMF', player.login),
            )
            await _dedi_post(payload, timeout=10)
        except Exception as e:
            logger.debug('[Dedimania] PlayerLeave error for %s: %s', player.login, e)

    if player.login in dedi_db.get('BannedLogins', []):
        dedi_db['BannedLogins'].remove(player.login)


# ---------------------------------------------------------------------------
# New challenge
# ---------------------------------------------------------------------------

async def _dedi_newchallenge(aseco: 'Aseco', challenge):
    dedi_db['Challenge'] = {}
    dedi_db['RecsValid'] = False
    dedi_db['TrackValid'] = False
    dedi_db['ServerMaxRank'] = int(dedi_db.get('MaxRank', 30) or 30)

    mode = getattr(aseco.server.gameinfo, 'mode', 0)

    if mode == 4:
        aseco.console('[Dedimania] Stunts: records ignored')
        await aseco.release_event('onDediRecsLoaded', False)
        return

    if (
        getattr(aseco.server, 'getGame', lambda: 'TMF')() == 'TMF'
        and bool(getattr(challenge, 'laprace', False))
        and int(getattr(challenge, 'forcedlaps', 0) or 0) != 0
        and mode in (1, 2, 5)
    ):
        aseco.console('[Dedimania] RoundForcedLaps != 0: records ignored')
        await aseco.release_event('onDediRecsLoaded', False)
        return

    if getattr(challenge, 'authortime', 0) < DEDI_MIN_AUTH:
        aseco.console('[Dedimania] Author time too short: ignored')
        await aseco.release_event('onDediRecsLoaded', False)
        return

    dedi_db['TrackValid'] = True

    if not _connected:
        await aseco.release_event('onDediRecsLoaded', False)
        return

    try:
        srv = await _server_info(aseco)
        pls = _collect_players(aseco)
        payload = _build_multicall(
            ('dedimania.CurrentChallenge',
             challenge.uid, challenge.name, challenge.environment,
             challenge.author, 'TMF', mode, srv, dedi_db['MaxRank'], pls),
        )
        results = await _dedi_post(payload)
        data = _extract(results, 0)

        if data and isinstance(data, dict):
            dedi_db['Challenge'] = data
            dedi_db['RecsValid'] = True
            if 'ServerMaxRecords' in data:
                dedi_db['ServerMaxRank'] = int(data['ServerMaxRecords'])
                dedi_db['MaxRank'] = int(data['ServerMaxRecords'])
            for pl in aseco.server.players.all():
                if not _is_server_login(aseco, pl.login) and not _is_lan_login(pl.login):
                    try:
                        pl.dedirank = int(dedi_db['ServerMaxRank'])
                    except Exception:
                        pass
            for rec in dedi_db['Challenge'].get('Records', []):
                if isinstance(rec, dict):
                    rec['NickName'] = rec.get('NickName', '').replace('\n', '')
            if dedi_db.get('ShowRecsBefore', 1) > 0:
                await _show_recs(aseco, challenge, before=True)
            await aseco.release_event('onDediRecsLoaded', True)
            return

        logger.debug('[Dedimania] Bad CurrentChallenge response: %s', str(data)[:200])

    except Exception as e:
        logger.debug('[Dedimania] NewChallenge error: %s', e)

    await aseco.release_event('onDediRecsLoaded', False)


def _get_rec_slice(recs: list[dict], show_min: int) -> tuple[int, list[dict]]:
    """
    Return (start_rank, slice_records), where start_rank is 1-based.
    If ShowRecsRange is disabled, just return the top N.
    If enabled, try to show a centered range around the best newly-improved record.
    """
    if not recs:
        return 1, []

    show_min = max(1, int(show_min or 1))

    if not dedi_db.get('ShowRecsRange', True):
        return 1, recs[:show_min]

    focus_idx = None
    for idx, rec in enumerate(recs):
        if isinstance(rec, dict) and rec.get('NewBest'):
            focus_idx = idx
            break

    if focus_idx is None:
        return 1, recs[:show_min]

    half = show_min // 2
    start = max(0, focus_idx - half)
    end = start + show_min

    if end > len(recs):
        end = len(recs)
        start = max(0, end - show_min)

    return start + 1, recs[start:end]


async def _show_recs(aseco: 'Aseco', challenge, before: bool = True):
    recs = dedi_db.get('Challenge', {}).get('Records', [])
    msgs = dedi_db.get('Messages', {}) or {}

    from pyxaseco.helpers import format_time, strip_colors

    name = strip_colors(getattr(challenge, 'name', ''))
    show_min = int(dedi_db.get('ShowMinRecs', 8) or 8)
    when_word = 'before' if before else 'after'

    if not recs:
        tpl = msgs.get(
            'RANKING_NONE',
            ['{#server}>> {#dedimsg}Dedimania Record rankings on {#highlite}{1}{#dedimsg} {2} this round: no records!']
        )
        header = tpl[0] if isinstance(tpl, list) else str(tpl)
        header = header.replace('{1}', name).replace('{2}', when_word)
        await aseco.client.query_ignore_result('ChatSendServerMessage', aseco.format_colors(header))
        return

    tpl = msgs.get(
        'RANKING',
        ['{#server}>> {#dedimsg}Dedimania Record rankings on {#highlite}{1}{#dedimsg} {2} this round:']
    )
    header = tpl[0] if isinstance(tpl, list) else str(tpl)
    header = header.replace('{1}', name).replace('{2}', when_word)

    start_rank, shown_recs = _get_rec_slice(recs, show_min)

    parts = []
    rank_no = start_rank
    for rec in shown_recs:
        if not isinstance(rec, dict):
            rank_no += 1
            continue

        who = rec.get('NickName', rec.get('Login', '?')) if dedi_db.get('ShowRecLogins') else rec.get('Login', '?')
        who = strip_colors(str(who)).replace('\n', '').replace('\r', '')
        score = int(rec.get('Best', 0) or 0)

        part = f'{{#rank}}{rank_no}.{{#dedirec}}{who}{{#dedirec}} [{{#highlite}}{format_time(score)}{{#dedirec}}]'
        if rec.get('NewBest'):
            part = f'{{#highlite}}>> {{#dedirec}}{part}'
        parts.append(part)
        rank_no += 1

    await aseco.client.query_ignore_result('ChatSendServerMessage', aseco.format_colors(header))
    if parts:
        await aseco.client.query_ignore_result('ChatSendServerMessage', aseco.format_colors(' '.join(parts)))

# ---------------------------------------------------------------------------
# End race
# ---------------------------------------------------------------------------

async def _dedi_endrace(aseco: 'Aseco', _data):
    if not _connected or not dedi_db.get('TrackValid') or not dedi_db.get('RecsValid'):
        return
    records = dedi_db.get('Challenge', {}).get('Records', [])
    times = [
        {'Login': r['Login'], 'Best': r['Best'],
         'Checks': ','.join(str(c) for c in r.get('Checks', []))}
        for r in records
        if isinstance(r, dict) and r.get('NewBest') and r.get('Best', 0) >= DEDI_MIN_TIME
    ]
    if not times:
        return
    times.sort(key=lambda x: x['Best'])
    try:
        ch   = aseco.server.challenge
        mode = getattr(aseco.server.gameinfo, 'mode', 0)
        nc   = len(times[0].get('Checks', '').split(',')) if times else 0
        payload = _build_multicall(
            ('dedimania.ChallengeRaceTimes',
             ch.uid, ch.name, ch.environment, ch.author,
             'TMF', mode, nc, dedi_db['MaxRank'], times),
        )
        results = await _dedi_post(payload)
        data = _extract(results, 0)
        if data and isinstance(data, dict):
            dedi_db['Results'] = data

            new_records = data.get('Records', [])
            for rec in new_records:
                if isinstance(rec, dict):
                    rec['NickName'] = rec.get('NickName', '').replace('\n', '')

            if isinstance(dedi_db.get('Challenge'), dict):
                dedi_db['Challenge']['Records'] = list(new_records)

            if new_records and dedi_db.get('ShowRecsAfter', 1) > 0:
                await _show_recs(aseco, ch, before=False)
    except Exception as e:
        logger.debug('[Dedimania] EndRace error: %s', e)


# ---------------------------------------------------------------------------
# Player finish
# ---------------------------------------------------------------------------

async def _dedi_playerfinish(aseco: 'Aseco', finish_item):
    if isinstance(finish_item, list):
        if len(finish_item) < 3:
            return
        _uid, login, score = finish_item[0], finish_item[1], finish_item[2]
        player = aseco.server.players.get_player(login)
        is_new = True
    else:
        player = getattr(finish_item, 'player', None)
        if not player:
            return
        login = player.login
        score = finish_item.score
        is_new = getattr(finish_item, 'new', False)

    if not dedi_db.get('RecsValid') or score == 0:
        return

    mode = getattr(aseco.server.gameinfo, 'mode', 0)
    if mode == 4:
        return
    if mode == 3 and not is_new:
        return

    if not player or _is_server_login(aseco, login) or _is_lan_login(login):
        return

    if login in dedi_db.get('BannedLogins', []):
        msg_tpl = dedi_db.get('Messages', {}).get(
            'BANNED_FINISH',
            ['{#server}> {#error}Your finish is ignored because you are banned on Dedimania.']
        )
        msg = msg_tpl[0] if isinstance(msg_tpl, list) else str(msg_tpl)
        await aseco.client.query_ignore_result('ChatSendServerMessageToLogin', aseco.format_colors(msg), login)
        return

    try:
        from pyxaseco.plugins.plugin_checkpoints import checkpoints
        cp = checkpoints.get(login)
        if cp and getattr(cp, 'curr_cps', None):
            curr_fin = getattr(cp, 'curr_fin', score)
            last_cp = cp.curr_cps[-1]
            if (mode != 3 and score != curr_fin) or score != last_cp:
                aseco.console('[Dedimania] player {1} inconsistent finish/checks, ignored: {2}', login, score)
                return
    except Exception:
        cp = None

    from pyxaseco.helpers import format_time, strip_colors

    dedi_recs = dedi_db.get('Challenge', {}).get('Records', [])
    if not isinstance(dedi_recs, list):
        dedi_recs = []
        dedi_db.setdefault('Challenge', {})['Records'] = dedi_recs

    nickname = strip_colors(player.nickname)
    max_rank = max(
        int(dedi_db.get('ServerMaxRank', 30) or 30),
        int(getattr(player, 'dedirank', 30) or 30)
    )

    try:
        checks = list(getattr(cp, 'curr_cps', [])) if cp else []
    except Exception:
        checks = []

    for i in range(max_rank):
        existing_best = dedi_recs[i]['Best'] if i < len(dedi_recs) else None

        if existing_best is None or score < existing_best:
            # Find existing record for this player
            cur_rank, cur_score = -1, 0
            for rank, rec in enumerate(dedi_recs):
                if isinstance(rec, dict) and rec.get('Login') == login:
                    if score > rec.get('Best', 0):
                        return  # worse than own record
                    cur_rank, cur_score = rank, rec.get('Best', 0)
                    break

            diff = (cur_score - score) if cur_rank != -1 else 0

            newbest_rec = None

            if cur_rank != -1:
                if diff > 0:
                    dedi_recs[cur_rank].update({
                        'Best': score,
                        'Checks': checks,
                        'NewBest': True,
                    })

                if cur_rank > i:
                    rec = dedi_recs.pop(cur_rank)
                    dedi_recs.insert(i, rec)
                    newbest_rec = rec

                    msg = (
                        f'{{#server}}>> {{#highlite}}{nickname}{{#dedirec}} gained the '
                        f'{{#rank}}{i+1}{{#dedirec}}. Dedimania Record!  '
                        f'Time: {{#highlite}}{format_time(score)}{{#dedirec}} '
                        f'$n({{#rank}}{cur_rank+1}{{#highlite}} -{format_time(diff)}{{#dedirec}})'
                    )
                    if dedi_db.get('DisplayRecs') and i < dedi_db.get('LimitRecs', 10):
                        await aseco.client.query_ignore_result(
                            'ChatSendServerMessage',
                            aseco.format_colors(msg)
                        )

                elif diff > 0:
                    newbest_rec = dedi_recs[cur_rank]

                    msg = (
                        f'{{#server}}>> {{#highlite}}{nickname}{{#dedirec}} secured his/her '
                        f'{{#rank}}{cur_rank+1}{{#dedirec}}. Dedimania Record!  '
                        f'Time: {{#highlite}}{format_time(score)}{{#dedirec}} '
                        f'$n({{#rank}}{cur_rank+1}{{#highlite}} -{format_time(diff)}{{#dedirec}})'
                    )
                    if dedi_db.get('DisplayRecs') and cur_rank < dedi_db.get('LimitRecs', 10):
                        await aseco.client.query_ignore_result(
                            'ChatSendServerMessage',
                            aseco.format_colors(msg)
                        )

                elif diff == 0:
                    msg = (
                        f'{{#server}}>> {{#highlite}}{nickname}{{#dedirec}} equaled his/her '
                        f'{{#rank}}{cur_rank+1}{{#dedirec}}. Dedimania Record!  '
                        f'Time: {{#highlite}}{format_time(score)}'
                    )
                    if dedi_db.get('DisplayRecs') and cur_rank < dedi_db.get('LimitRecs', 10):
                        await aseco.client.query_ignore_result(
                            'ChatSendServerMessage',
                            aseco.format_colors(msg)
                        )

            else:
                new_rec = {
                    'Game': 'TMU',
                    'Login': login,
                    'NickName': player.nickname,
                    'Best': score,
                    'Checks': checks,
                    'NewBest': True,
                }
                dedi_recs.insert(i, new_rec)
                newbest_rec = new_rec

                msg = (
                    f'{{#server}}>> {{#highlite}}{nickname}{{#dedirec}} claimed the '
                    f'{{#rank}}{i+1}{{#dedirec}}. Dedimania Record!  '
                    f'Time: {{#highlite}}{format_time(score)}'
                )
                if dedi_db.get('DisplayRecs') and i < dedi_db.get('LimitRecs', 10):
                    await aseco.client.query_ignore_result(
                        'ChatSendServerMessage',
                        aseco.format_colors(msg)
                    )

            # Keep the in-memory Dedimania list fully re-ranked after inserts/moves.
            # Without this, pushed-down records can keep stale Pos/rank values until
            # a later full refresh, which breaks live widgets that rely on the cache.
            for _idx, _rec in enumerate(dedi_recs):
                if isinstance(_rec, dict):
                    _rec['Pos'] = _idx + 1
                    _rec['rank'] = _idx + 1

            if isinstance(newbest_rec, dict) and newbest_rec.get('NewBest'):
                aseco.console(
                    '[Dedimania] player {1} finished with {2} and took the {3}. WR place!',
                    login, score, i + 1
                )
                await aseco.release_event('onDedimaniaRecord', newbest_rec)

            return

# ---------------------------------------------------------------------------
# Support
# ---------------------------------------------------------------------------

def _is_lan_login(login: str) -> bool:
    login = (login or "").strip().lower()
    return login.startswith("lan_") or login == "lan"

def _is_server_login(aseco: 'Aseco', login: str) -> bool:
    if not login:
        return False
    lgn = str(login).lower()
    server_login = str(getattr(aseco.server, 'serverlogin', '')).lower()
    if lgn == server_login:
        return True
    dedi_login = str(dedi_db.get('Login', '')).lower()
    return bool(dedi_login and lgn == dedi_login)

def _collect_players(aseco: 'Aseco') -> list:
    result = []
    for pl in aseco.server.players.all():
        if _is_server_login(aseco, pl.login) or _is_lan_login(pl.login):
            continue
        result.append({
            'Login':    pl.login,
            'Nation':   getattr(pl, 'nation', ''),
            'TeamName': getattr(pl, 'teamname', ''),
            'TeamId':   -1,
            'IsSpec':   bool(pl.isspectator),
            'Ranking':  getattr(pl, 'ladderrank', 0),
            'IsOff':    getattr(pl, 'isofficial', False),
        })
    return result


async def _get_next_uid(aseco: 'Aseco') -> str:
    try:
        from pyxaseco.plugins.plugin_rasp_jukebox import jukebox
        if jukebox:
            first = jukebox[0]
            if isinstance(first, dict):
                return first.get('uid', '') or ''
    except Exception:
        pass

    try:
        current = await aseco.client.query('GetCurrentChallengeIndex')
        track = await aseco.client.query('GetChallengeList', 1, int(current) + 1)
        if track and isinstance(track, list):
            first = track[0] if track else None
            if isinstance(first, dict):
                return first.get('UId', '') or first.get('Uid', '') or ''
    except Exception:
        pass

    try:
        track = await aseco.client.query('GetChallengeList', 1, 0)
        if track and isinstance(track, list):
            first = track[0] if track else None
            if isinstance(first, dict):
                return first.get('UId', '') or first.get('Uid', '') or ''
    except Exception:
        pass

    return ''


async def _server_info(aseco: 'Aseco') -> dict:
    try:
        opts = await aseco.client.query('GetServerOptions') or {}
    except Exception:
        opts = {}

    players = aseco.server.players.all()
    return {
        'SrvName':    opts.get('Name', aseco.server.name),
        'Comment':    opts.get('Comment', ''),
        'Private':    bool(opts.get('Password', '')),
        'SrvIP':      '',
        'SrvPort':    0,
        'XmlrpcPort': 0,
        'NumPlayers': sum(1 for p in players if not p.isspectator),
        'MaxPlayers': opts.get('CurrentMaxPlayers', 20),
        'NumSpecs':   sum(1 for p in players if p.isspectator),
        'MaxSpecs':   opts.get('CurrentMaxSpectators', 10),
        'LadderMode': opts.get('CurrentLadderMode', 0),
        'NextFiveUID': await _get_next_uid(aseco),
    }
