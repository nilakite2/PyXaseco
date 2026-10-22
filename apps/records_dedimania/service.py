"""
dedimania_service.py - Port of plugins/plugin.dedimania.php

Protocol: Every HTTP POST is a system.multicall that starts with
dedimania.Authenticate, followed by actual API call(s), then
dedimania.WarningsAndTTR.

Config:
  - settings.toml
  - apps/records_dedimania/app_defaults.toml
  - .env
"""

from __future__ import annotations
import logging
import pathlib
import sys
import time
import xmlrpc.client
from typing import TYPE_CHECKING

from pyxaseco.app_config import AppSetting, AppSettingsSchema, as_int, bind_app_settings
from pyxaseco.core.config import _load_dotenv, _env
from pyxaseco.core.background_jobs import JobEnvelope, JobPolicy, Admission
from pyxaseco.core.http_sessions import HttpPolicy, request_timeout
from pyxaseco.core.external_io import read_limited
from pyxaseco.core.service_health import observe_request
from pyxaseco.core.aseco import PYXASECO_VERSION

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco

logger = logging.getLogger(__name__)

PLUGIN_METADATA = {
    'display_name': 'Dedimania Service',
    'description': 'Provides Dedimania connectivity, state cache, and record synchronization.',
    'provides': ['service/records_dedimania', 'records_dedimania', 'service/dedimania', 'dedimania'],
}

DEDI_TIMEOUT  = 1800
DEDI_REFRESH  = 240
DEDI_MIN_AUTH = 8000
DEDI_MIN_TIME = 6000

dedi_db: dict   = {}
_connected      = False
_bad_time: float = 0.0
_last_sent: float = 0.0


DEDI_SETTINGS_SCHEMA = AppSettingsSchema(
    app_id='records_dedimania',
    description='Typed Records Dedimania app defaults.',
    settings=(
        AppSetting('dedi_timeout', DEDI_TIMEOUT, as_int, 'Dedimania timeout threshold in seconds.', 'network'),
        AppSetting('dedi_refresh', DEDI_REFRESH, as_int, 'Dedimania refresh interval in seconds.', 'network'),
    ),
)


def register(aseco: 'Aseco'):
    global _runtime_aseco
    _runtime_aseco = aseco
    aseco.register_service(
        'service/records_dedimania',
        sys.modules[__name__],
        owner='service/records_dedimania',
        aliases=['records_dedimania', 'service/dedimania', 'dedimania'],
    )
    aseco.register_event('onSync',             _dedi_init)
    aseco.register_event('onEverySecond',      _dedi_update)
    aseco.register_event('onPlayerConnect',    _dedi_playerconnect)
    aseco.register_event('onPlayerDisconnect', _dedi_playerdisconnect)
    aseco.register_event('onNewChallenge',     _dedi_newchallenge)
    aseco.register_event('onRestartChallenge', _dedi_restart)
    aseco.register_event('onEndRace',          _dedi_endrace)
    aseco.register_event('onShutdown',         _dedi_endrace)
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
        'Version':     PYXASECO_VERSION,
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
    session = _runtime_aseco.jobs.http.get('dedimania', HttpPolicy())
    with observe_request(_runtime_aseco, 'dedimania') as sample:
        async with session.post(dedi_db.get('Url', 'http://dedimania.net:8002/Dedimania'),
                            data=payload, headers={'Content-Type': 'text/xml'},
                            timeout=request_timeout(timeout)) as response:
            if sample is not None:
                sample.http_status = response.status
            response.raise_for_status()
            body = await read_limited(response, 4 * 1024 * 1024)
        results, _ = xmlrpc.client.loads(body)
        if results and isinstance(results[0], list):
            results = results[0]
        if sample is not None and not _authenticated(results):
            sample.status = 'API rejected'
        return results


def _authenticated(results):
    auth = results[0] if isinstance(results, (list, tuple)) and results else None
    if isinstance(auth, list) and len(auth) == 1:
        auth = auth[0]
    return auth is True


async def _submit(aseco, calls, apply, *, current_map=True, key=None):
    job = JobEnvelope.capture(aseco.capture_job_context(), {'calls': calls})
    async def operation(envelope):
        return await _dedi_post(_build_multicall(*envelope.payload()['calls']))
    async def completed(result):
        global _connected, _bad_time
        valid = result.status == 'completed' and _authenticated(result.value)
        if not valid:
            _connected, _bad_time = False, time.time()
            reason = result.failure_label if result.status != 'completed' else 'authentication rejected'
            logger.warning('[Dedimania] Queued request unavailable (%s); reconnect deferred', reason)
        await apply(result.value if valid else None)
    outcome = aseco.jobs.service('dedimania', JobPolicy(deadline_seconds=120)).submit(
        job, operation, completed, current_map=current_map, dedupe_key=key)
    if outcome not in (Admission.ACCEPTED, Admission.DUPLICATE):
        logger.warning('[Dedimania] Request not admitted (%s)', outcome.value)
    return outcome


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
    global dedi_db, _connected, _bad_time, _last_sent, DEDI_TIMEOUT, DEDI_REFRESH
    _connected, _bad_time, _last_sent = False, 0.0, 0.0

    try:
        base = pathlib.Path(getattr(aseco, '_base_dir', '.'))
        _load_dotenv(base / '.env')
        _load_dotenv('.env')

        dedi_db = {
            'Url':            'http://dedimania.net:8002/Dedimania',
            'Name':           'Dedimania',
            'Welcome':        '',
            'TimeoutMsg':     '',
            'LogNews':        False,
            'ShowWelcome':    True,
            'ShowMinRecs':    8,
            'ShowRecsBefore': 1,
            'ShowRecsAfter':  1,
            'ShowRecsRange':  True,
            'DisplayRecs':    True,
            'RecsInWindow':   False,
            'ShowRecLogins':  True,
            'LimitRecs':      10,
            'MaxRank':        30,
            'ServerMaxRank':  30,
            'Login':          _env('DEDI_LOGIN'),
            'Password':       _env('DEDI_PASSWORD'),
            'Nation':         _env('DEDI_NATION'),
            'Packmask':       aseco.server.packmask,
            'Messages':       {},
            'RecsValid':      False,
            'TrackValid':     False,
            'BannedLogins':   [],
            'Challenge':      {},
            'Results':        {},
            'News':           [],
        }

        try:
            from pyxaseco.message_loader import overlay_section
            overlay_section(dedi_db['Messages'], 'dedi_messages', strip_prefix='dedi_', base_dir=base)
        except Exception as exc:
            logger.warning('[Dedimania] messages config overlay failed: %s', exc)

        try:
            from pyxaseco.settings_loader import overlay_dedimania
            overlay_dedimania(dedi_db, base)
        except Exception as exc:
            logger.warning('[Dedimania] settings config overlay failed: %s', exc)

        try:
            typed_settings = bind_app_settings(DEDI_SETTINGS_SCHEMA, base)
            DEDI_TIMEOUT = typed_settings.dedi_timeout
            DEDI_REFRESH = typed_settings.dedi_refresh
        except Exception as exc:
            logger.warning('[Dedimania] app defaults overlay failed: %s', exc)

        if not dedi_db['Login'] or dedi_db['Login'] in ('', 'YOUR_SERVER_LOGIN'):
            aseco.console('[Dedimania] Not configured - skipping.')
            return

        aseco.console('************* (Dedimania) *************')
        _record_delivery(aseco)
        await _connect(aseco)
        aseco.console('------------- (Dedimania) -------------')
        _last_sent = time.time()

    except Exception as e:
        logger.warning('[Dedimania] Init error: %s', e)


async def _connect(aseco: 'Aseco'):
    global _bad_time
    _bad_time = time.time()  # admission failures must not start a retry storm
    async def apply(results):
        global _connected, _bad_time
        validate = _extract(results, 0)
        if isinstance(validate, dict) and validate.get('Status'):
            _connected = True
            dedi_db['News'] = validate.get('Messages', []) or []
            aseco.console('* Dedimania: connection OK!')
            if dedi_db.get('LogNews'):
                for news in dedi_db['News']:
                    if isinstance(news, dict):
                        aseco.console('* NEWS ({1}, {2}): {3}', dedi_db.get('Name', 'Dedimania'),
                                      news.get('Date', ''), news.get('Text', ''))
            await _dedi_newchallenge(aseco, aseco.server.challenge, preserve_finishes=True)
            for player in aseco.server.players.all():
                await _dedi_playerconnect(aseco, player)
        else:
            _connected, _bad_time = False, time.time()
            logger.warning('[Dedimania] Authentication unavailable/rejected; retry after configured timeout')
    await _submit(aseco, [('dedimania.ValidateAccount',)], apply, current_map=False, key='auth')


# ---------------------------------------------------------------------------
# Periodic keep-alive
# ---------------------------------------------------------------------------

async def _dedi_update(aseco: 'Aseco', _param=None):
    global _last_sent, _connected, _bad_time
    if not dedi_db or not dedi_db.get('Login'):
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
    srv, players = await _server_info(aseco), _collect_players(aseco)
    mode = getattr(aseco.server.gameinfo, 'mode', 1)
    async def apply(_results):
        return
    await _submit(aseco, [('dedimania.UpdateServerPlayers', 'TMF', mode, srv, players)],
                  apply, current_map=False, key='announce')


# ---------------------------------------------------------------------------
# Player events
# ---------------------------------------------------------------------------

async def _dedi_playerconnect(aseco: 'Aseco', player):
    login, nickname = str(player.login), str(player.nickname)
    if _connected and not _is_server_login(aseco, login) and not _is_lan_login(login):
        calls = [('dedimania.PlayerArrive', 'TMF', login, nickname,
                  getattr(player, 'nation', ''), getattr(player, 'teamname', ''),
                  getattr(player, 'ladderrank', 0), bool(player.isspectator),
                  bool(getattr(player, 'isofficial', False)))]
        async def apply(results):
            if aseco.server.players.get_player(login) is not player:
                return
            data = _extract(results, 0)
            if not isinstance(data, dict):
                return
            player.dedirank = int(data.get('MaxRank') or dedi_db.get('ServerMaxRank', 30))
            if int(data.get('Status', 0) or 0) % 2 and login not in dedi_db['BannedLogins']:
                dedi_db['BannedLogins'].append(login)
                template = dedi_db.get('Messages', {}).get('BANNED_LOGIN',
                    ['{#server}>> {#highlite}{1}{#dedimsg} ({2}) is banned on Dedimania - finishes ignored!'])
                message = (template[0] if isinstance(template, list) else str(template)).replace('{1}', nickname).replace('{2}', login)
                await aseco.client.query_ignore_result('ChatSendServerMessage', aseco.format_colors(message))
        await _submit(aseco, calls, apply, current_map=False)
    if dedi_db.get('ShowWelcome') and dedi_db.get('Welcome'):
        await aseco.client.query_ignore_result('ChatSendServerMessageToLogin',
            aseco.format_colors('{#server}> ' + dedi_db['Welcome'].replace('{br}', '\n')), login)


async def _dedi_playerdisconnect(aseco: 'Aseco', player):
    login = str(player.login)
    if _connected and not _is_server_login(aseco, login) and not _is_lan_login(login):
        async def apply(_results):
            return
        await _submit(aseco, [('dedimania.PlayerLeave', 'TMF', login)], apply, current_map=False)
    if login in dedi_db.get('BannedLogins', []):
        dedi_db['BannedLogins'].remove(login)


# ---------------------------------------------------------------------------
# New challenge
# ---------------------------------------------------------------------------

async def _dedi_newchallenge(aseco: 'Aseco', challenge, *, preserve_finishes=False):
    dedi_db['Challenge'] = {}
    if not preserve_finishes:
        dedi_db['CapturedFinishes'] = {}
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

    srv, players = await _server_info(aseco), _collect_players(aseco)
    calls = [('dedimania.CurrentChallenge', challenge.uid, challenge.name, challenge.environment,
              challenge.author, 'TMF', mode, srv, dedi_db['MaxRank'], players)]
    async def apply(results):
        data = _extract(results, 0)
        if (not isinstance(data, dict) or not isinstance(data.get('Records'), list)
                or 'faultCode' in data):
            await aseco.release_event('onDediRecsLoaded', False)
            return
        # Finishes captured while the lookup/authentication was pending are newer
        # than the remote snapshot; keep their times and checkpoint arrays.
        records = {rec['Login']: dict(rec) for rec in data['Records']
                   if isinstance(rec, dict) and rec.get('Login')}
        for login, finish in dedi_db.get('CapturedFinishes', {}).items():
            previous = records.get(login)
            if previous is None or finish['Best'] < int(previous.get('Best') or 0):
                player = aseco.server.players.get_player(login)
                records[login] = {**(previous or {}), 'Login': login,
                                 'NickName': finish.get('NickName') or getattr(player, 'nickname', login),
                                 'Best': finish['Best'], 'NewBest': True,
                                 'Checks': [int(cp) for cp in finish['Checks'].split(',') if cp]}
        data['Records'] = sorted(records.values(), key=lambda rec: rec['Best'])
        dedi_db['Challenge'], dedi_db['RecsValid'] = data, True
        dedi_db['ServerMaxRank'] = int(data.get('ServerMaxRecords') or dedi_db.get('MaxRank', 30))
        dedi_db['MaxRank'] = dedi_db['ServerMaxRank']
        for player in aseco.server.players.all():
            if not _is_server_login(aseco, player.login) and not _is_lan_login(player.login):
                player.dedirank = dedi_db['ServerMaxRank']
        for rec in data.get('Records', []):
            rec['NickName'] = str(rec.get('NickName', '')).replace('\n', '')
        if dedi_db.get('ShowRecsBefore', 1) > 0:
            await _show_recs(aseco, challenge, before=True)
        await aseco.release_event('onDediRecsLoaded', True)
    await _submit(aseco, calls, apply, key='current')


async def _show_recs(aseco: 'Aseco', challenge, before: bool = True):
    from .commands import show_dedirecs

    mode = 1 if before else 3
    await show_dedirecs(
        aseco,
        getattr(challenge, 'name', ''),
        getattr(challenge, 'uid', ''),
        dedi_db.get('Challenge', {}).get('Records', []),
        None,
        mode,
        0,
    )

# ---------------------------------------------------------------------------
# End race
# ---------------------------------------------------------------------------

async def _dedi_restart(aseco, _param):
    await _dedi_endrace(aseco, None)
    await _dedi_newchallenge(aseco, aseco.server.challenge)


async def _dedi_endrace(aseco: 'Aseco', _data):
    if not dedi_db.get('TrackValid'):
        return
    records = dedi_db.get('Challenge', {}).get('Records', [])
    times = [{'Login': r['Login'], 'Best': r['Best'],
              'Checks': ','.join(str(c) for c in r.get('Checks', []))}
             for r in records if isinstance(r, dict) and r.get('NewBest')
             and r.get('Best', 0) >= DEDI_MIN_TIME]
    captured = dict(dedi_db.get('CapturedFinishes', {}))
    by_login = {row['Login']: row for row in times}
    for login, row in captured.items():
        if row['Best'] >= DEDI_MIN_TIME and (login not in by_login or row['Best'] < by_login[login]['Best']):
            by_login[login] = {key: row[key] for key in ('Login', 'Best', 'Checks')}
    times = list(by_login.values())
    if not times:
        return
    times.sort(key=lambda row: row['Best'])
    ch = aseco.server.challenge
    calls = [('dedimania.ChallengeRaceTimes', ch.uid, ch.name, ch.environment, ch.author,
              'TMF', aseco.server.gameinfo.mode, len(times[0]['Checks'].split(',')),
              dedi_db['MaxRank'], times)]
    await _record_delivery(aseco).retain({'calls': calls})
    dedi_db['CapturedFinishes'] = {}
    for record in records:
        record['NewBest'] = False


def _record_delivery(aseco):
    from pyxaseco.core.retained_delivery import PreparationDeferred, delivery
    def ready():
        return _connected
    async def prepare(data):
        if not ready():
            raise PreparationDeferred('Dedimania authentication is not ready')
        return data
    async def send(data):
        results = await _dedi_post(_build_multicall(*data['calls']))
        reply = _extract(results, 0)
        if (not _authenticated(results) or not isinstance(reply, dict)
                or not isinstance(reply.get('Records'), list) or 'faultCode' in reply):
            raise RuntimeError('Unconfirmed Dedimania result')
        return reply
    async def apply(_data, response, current):
        if not current:
            return
        dedi_db['Results'] = response
        records = response.get('Records', [])
        for rec in records:
            rec['NickName'] = str(rec.get('NickName', '')).replace('\n', '')
        dedi_db['Challenge']['Records'] = records
        if records and dedi_db.get('ShowRecsAfter', 1) > 0:
            await _show_recs(aseco, aseco.server.challenge, before=False)
    async def failed(_result):
        global _connected, _bad_time
        if _connected:
            _connected, _bad_time = False, time.time()
    return delivery(aseco, 'dedimania', send, apply, prepare=prepare, on_failure=failed, ready=ready)


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
        _uid = getattr(getattr(finish_item, 'challenge', None), 'uid', '')

    if isinstance(_uid, str) and _uid and _uid != aseco.server.challenge.uid:
        return

    if score == 0 or not dedi_db.get('TrackValid'):
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
        from apps.platform_core.checkpoints import checkpoints
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

    checks = list(getattr(cp, 'curr_cps', [])) if cp else []
    captured = dedi_db.setdefault('CapturedFinishes', {})
    old = captured.get(login)
    if old is None or score < old['Best']:
        captured[login] = {'Login': login, 'Best': score,
                           'Checks': ','.join(str(c) for c in checks),
                           'NickName': str(player.nickname)}
    if not dedi_db.get('RecsValid'):
        return

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
        from apps.jukebox.jukebox import jukebox
        if jukebox:
            if isinstance(jukebox, dict):
                first_uid = next(iter(jukebox), '')
                first = jukebox.get(first_uid)
                if isinstance(first, dict):
                    return first.get('uid', '') or first_uid or ''
            elif isinstance(jukebox, list):
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

