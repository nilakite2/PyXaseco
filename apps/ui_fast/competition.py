"""FAST-inspired cumulative Team matches, independent of the selected UI style."""

from copy import deepcopy
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import secrets
from time import monotonic
from uuid import uuid4

from pyxaseco.core.file_io import file_io
from pyxaseco.models import Gameinfo
from . import reports
from .team_rounds import TeamRounds


logger = logging.getLogger(__name__)
SERVICE = 'competition/team'
EVENT = 'onTeamMatchChanged'
MAX_SCORE = 2147483647
MAX_ROUNDS = 64
DEFAULT_RULES = dict(scoring='native', target=0, win_margin=1)


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def empty_state():
    return dict(version=1, revision=0, server_login='', match_id='', state='idle',
                names=['Blue Team', 'Red Team'], maps=[], adjustments=[])


def totals(data):
    scores = [0, 0]
    scoring = data.get('rules', DEFAULT_RULES)['scoring']
    for row in data['maps']:
        if not row.get('void', False):
            for team in (0, 1):
                scores[team] += (row['scores'][team] if scoring == 'native'
                                 else int(row['scores'][team] > row['scores'][1 - team]))
    for row in data['adjustments']:
        if row['action'] == 'score':
            for team in (0, 1):
                scores[team] += row['delta'][team]
    return scores


def reached_target(data):
    rules = data.get('rules', DEFAULT_RULES)
    blue, red = totals(data)
    return bool(rules['target'] and max(blue, red) >= rules['target']
                and abs(blue - red) >= rules['win_margin'])


def valid_rounds(row):
    rounds = row.get('rounds', [])
    omitted = row.get('rounds_omitted', 0)
    if (not isinstance(rounds, list) or len(rounds) > MAX_ROUNDS or
            type(omitted) is not int or omitted < 0):
        return False
    for round_ in rounds:
        if (not isinstance(round_, dict) or type(round_.get('number')) is not int
                or round_['number'] < 1 or 'points' not in round_
                or not isinstance(round_.get('players'), list) or len(round_['players']) > 256):
            return False
        points = round_['points']
        if points is not None and (not isinstance(points, list) or len(points) != 2 or
                                   any(type(n) is not int or n < 0 for n in points)):
            return False
        for player in round_['players']:
            if (not isinstance(player, dict) or not isinstance(player.get('login'), str)
                    or not isinstance(player.get('name'), str) or type(player.get('team')) is not int
                    or player['team'] not in (0, 1) or any(
                        key not in player or (player[key] is not None and
                            (type(player[key]) is not int or player[key] < 0))
                        for key in ('time_ms', 'checkpoint', 'rank', 'points'))):
                return False
    return True


def team_scores(rows):
    """Never infer team identity from ranking order: the winner can be Red."""
    if not isinstance(rows, list) or len(rows) != 2:
        raise ValueError('Expected two team ranking entries.')
    result = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Invalid team ranking entry.')
        team = row.get('TeamId')
        if team is None and str(row.get('Login', '')) in ('0', '1'):
            team = int(row['Login'])
        score = row.get('Score')
        if (type(team) is not int or team not in (0, 1) or team in result or
                type(score) is not int or not 0 <= score <= MAX_SCORE):
            raise ValueError('Missing/invalid team identifier or score.')
        result[team] = score
    return [result[0], result[1]]


def read_state(path):
    if not path.exists():
        return empty_state()
    if path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError('Team match state file is too large.')
    data = json.loads(path.read_text(encoding='utf-8'))
    if (not isinstance(data, dict) or data.get('version') != 1 or
            data.get('state') not in ('idle', 'armed', 'running', 'paused', 'stopped') or
            type(data.get('revision')) is not int or data['revision'] < 0 or
            not isinstance(data.get('server_login'), str) or not isinstance(data.get('match_id'), str) or
            not isinstance(data.get('names'), list) or len(data['names']) != 2 or
            any(not isinstance(name, str) or not 1 <= len(name.strip()) <= 80 for name in data['names']) or
            not isinstance(data.get('maps'), list) or not isinstance(data.get('adjustments'), list)):
        raise ValueError('Invalid team match state file.')
    ids = set()
    rules = data.get('rules', DEFAULT_RULES)
    if (not isinstance(rules, dict) or rules.get('scoring') not in ('native', 'map_wins')
            or type(rules.get('target')) is not int or not 0 <= rules['target'] <= MAX_SCORE
            or type(rules.get('win_margin')) is not int or not 1 <= rules['win_margin'] <= MAX_SCORE):
        raise ValueError('Invalid scoring rules in team match state.')
    for row in data['maps']:
        if (not isinstance(row, dict) or not isinstance(row.get('id'), str) or not row['id'] or
                row['id'] in ids or not isinstance(row.get('uid'), str) or
                not isinstance(row.get('name'), str) or type(row.get('void')) is not bool or
                not isinstance(row.get('scores'), list) or len(row['scores']) != 2 or
                any(type(score) is not int or not 0 <= score <= MAX_SCORE for score in row['scores'])
                or not valid_rounds(row)):
            raise ValueError('Invalid map result in team match state.')
        ids.add(row['id'])
    for row in data['adjustments']:
        if not isinstance(row, dict) or row.get('action') not in ('score', 'undo', 'name'):
            raise ValueError('Invalid adjustment in team match state.')
        if row['action'] == 'score' and (not isinstance(row.get('delta'), list) or len(row['delta']) != 2 or
                any(type(score) is not int for score in row['delta'])):
            raise ValueError('Invalid score adjustment in team match state.')
    if (any(score < 0 for score in totals(data)) or
            (not data['match_id'] and (data['state'] != 'idle' or data['maps'] or data['adjustments'])) or
            (data['match_id'] and data['state'] == 'idle')):
        raise ValueError('Inconsistent team match state.')
    return data


def write_state(path, data):
    raw = json.dumps(data, ensure_ascii=False, indent=2) + '\n'
    if len(raw.encode('utf-8')) > 8 * 1024 * 1024:
        raise ValueError('Team match history is full; export/reset it before continuing.')
    temporary = path.with_suffix('.json.tmp')
    try:
        with temporary.open('w', encoding='utf-8', newline='\n') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class TeamCompetition:
    def __init__(self):
        self.data = empty_state()
        self.enabled = self.ready = False
        self.error = ''
        self.path = None
        self.attempt = None
        self.pending = {}
        self.default_names = ['Blue Team', 'Red Team']
        self.default_rules = dict(DEFAULT_RULES)
        self.rounds = TeamRounds()
        self.round_history = self.show_round = False

    def register(self, aseco):
        aseco.register_service(SERVICE, self, owner='ui_fast')
        for event, callback in (('onNewChallenge', self.begin), ('onRestartChallenge', self.restart),
                                ('onEndRace', self.end), ('onPlayerDisconnect', self.disconnect),
                                ('onBeginRound', self.round_start), ('onEndRound', self.round_end),
                                ('onCheckpoint', self.round_checkpoint), ('onPlayerFinish1', self.round_finish),
                                ('onPlayerInfoChanged', self.round_info), ('onPlayerConnect2', self.round_info)):
            aseco.register_event(event, callback)

    async def configure(self, aseco, values):
        self.default_names = [values['competition/blue'], values['competition/red']]
        self.default_rules = {key: values.get('competition/' + key, default)
                              for key, default in DEFAULT_RULES.items()}
        self.round_history = values.get('competition/round_history', True)
        self.show_round = values.get('competition/show_round', True)
        if not self.ready:
            self.path = Path(aseco._base_dir) / 'apps' / 'ui_fast' / 'team_match.json'
            try:
                self.data = await file_io(read_state, self.path)
                if self.data['match_id'] and self.data['server_login'] != aseco.server.serverlogin:
                    raise ValueError('Saved match belongs to a different dedicated-server login.')
                if self.data['state'] in ('armed', 'running'):
                    recovered = deepcopy(self.data)
                    recovered['state'] = 'paused'
                    await self.commit(recovered)
            except (OSError, ValueError) as error:
                self.error = str(error)
                self.data = empty_state()
                logger.error('[FAST Match] Cannot restore match; tracking disabled, saved file retained: %s', error)
            self.ready = True
        if not values['competition/enabled'] and self.data['state'] in ('armed', 'running') and not self.error:
            data = deepcopy(self.data)
            data['state'] = 'paused'
            self.attempt = None
            await self.commit(data)
        self.enabled = values['competition/enabled']
        if not self.enabled or not (self.round_history or self.show_round):
            self.rounds.reset()
        await self.notify(aseco)

    def snapshot(self, *, details=False):
        if not self.enabled or not self.data['match_id']:
            return None
        snapshot = self.data if details else {
            **self.data, 'maps': [{key: value for key, value in row.items() if key != 'rounds'}
                                 for row in self.data['maps']],
        }
        data = deepcopy(snapshot)
        if self.error:
            data['state'], data['error'] = 'paused', self.error
        data['totals'] = totals(data)
        data['counted'] = sum(not row['void'] for row in data['maps'])
        data['target_reached'] = reached_target(data)
        return data

    async def commit(self, data):
        data['revision'] = self.data['revision'] + 1
        try:
            await file_io(write_state, self.path, data)
        except (OSError, ValueError) as error:
            self.attempt = None
            self.error = str(error)
            raise ValueError('Cannot save FAST match; collection halted. Saved results were not overwritten.') from error
        self.data = data
        self.pending.clear()

    async def notify(self, aseco):
        await aseco.release_event(EVENT, self.snapshot())

    async def begin(self, aseco, challenge):
        self.attempt = None
        self.rounds.reset()
        if (not self.enabled or self.error or getattr(aseco, 'startup_phase', False) or
                self.data['state'] not in ('armed', 'running') or
                aseco.server.gameinfo.mode != Gameinfo.TEAM or getattr(aseco, 'warmup_phase', False)):
            return
        data = deepcopy(self.data)
        data['state'] = 'running'
        await self.commit(data)
        self.attempt = dict(id=uuid4().hex, uid=challenge.uid, name=challenge.name,
                            generation=aseco._map_generation,
                            limit=int(getattr(aseco.server.gameinfo, 'teamlimit', 0) or 0),
                            rounds=[], rounds_omitted=0)
        await self.notify(aseco)

    async def restart(self, aseco, _data=None):
        self.attempt = None
        self.rounds.reset()
        await self.notify(aseco)

    async def round_start(self, aseco, _data=None):
        if (self.enabled and not aseco.warmup_phase and aseco.server.gameinfo.mode == Gameinfo.TEAM
                and (self.show_round or (self.round_history and self.attempt))):
            self.rounds.begin(aseco)

    async def round_checkpoint(self, aseco, data):
        if isinstance(data, (list, tuple)):
            self.rounds.checkpoint(aseco, data)

    async def round_finish(self, aseco, record):
        self.rounds.finish(aseco, record)

    async def round_info(self, aseco, player):
        self.rounds.info(aseco, player)

    def retain_round(self, attempt, result):
        if not (attempt and result and self.round_history):
            return
        if len(attempt['rounds']) < MAX_ROUNDS:
            attempt['rounds'].append(result)
        else:
            attempt['rounds_omitted'] += 1

    async def round_end(self, aseco, _data=None):
        self.retain_round(self.attempt, self.rounds.end(aseco))

    async def end(self, aseco, params):
        attempt = self.attempt
        if not attempt or not self.enabled or self.error or self.data['state'] != 'running':
            return
        if (not isinstance(params, (list, tuple)) or len(params) < 3 or params[2] or
                not isinstance(params[1], dict) or
                params[1].get('UId', params[1].get('Uid')) != attempt['uid'] or
                aseco._map_generation != attempt['generation']):
            return
        self.attempt = None
        if len(params) > 4 and params[4]:
            return
        try:
            scores = team_scores(params[0])
        except ValueError:
            logger.warning('[FAST Match] Final team scores unavailable; map not counted.')
            return
        # A skip also emits EndChallenge. Require native completion, not merely
        # a final ranking; unknown/zero-limit formats need separate support.
        if attempt['limit'] <= 0 or max(scores) < attempt['limit']:
            logger.info('[FAST Match] Map not counted: native Team points limit was not reached.')
            return
        if any(row['id'] == attempt['id'] for row in self.data['maps']):
            return
        if any(point[0] == 'finished' for point in self.rounds.progress.values()):
            self.retain_round(attempt, self.rounds.end(aseco))
        data = deepcopy(self.data)
        data['maps'].append(dict(id=attempt['id'], uid=attempt['uid'], name=attempt['name'],
                                 scores=scores, void=False, recorded_at=timestamp(),
                                 rounds=attempt['rounds'], rounds_omitted=attempt['rounds_omitted']))
        if reached_target(data):
            data['state'] = 'stopped'
        await self.commit(data)
        await self.notify(aseco)

    def require_admin(self, aseco, player):
        if not (aseco.is_master_admin(player) or aseco.is_admin(player)):
            raise ValueError('Only Admins and MasterAdmins may manage FAST matches.')
        if not self.enabled:
            raise ValueError('Enable ui_fast.competition.enabled in //apps config ui_fast first.')
        if self.error:
            raise ValueError('FAST match state needs attention: ' + self.error)
        if not self.data['match_id']:
            raise ValueError('No match exists. Use //tmatch start.')

    async def set_score(self, aseco, player, scores):
        self.require_admin(aseco, player)
        if len(scores) != 2 or any(type(score) is not int or not 0 <= score <= MAX_SCORE for score in scores):
            raise ValueError('Use two non-negative whole scores, at most 2147483647 each.')
        data = deepcopy(self.data)
        previous = totals(data)
        data['adjustments'].append(dict(action='score', actor=player.login, at=timestamp(),
                                        delta=[scores[i] - previous[i] for i in (0, 1)]))
        await self.commit(data)
        await self.notify(aseco)

    async def set_name(self, aseco, player, index, name):
        self.require_admin(aseco, player)
        if index not in (0, 1) or not 1 <= len(name.strip()) <= 80 or any(ord(c) < 32 for c in name):
            raise ValueError('Team names must contain 1-80 characters without line breaks.')
        data = deepcopy(self.data)
        data['names'][index] = name.strip()
        data['adjustments'].append(dict(action='name', actor=player.login, at=timestamp(),
                                        team=index, name=name.strip()))
        await self.commit(data)
        await self.notify(aseco)

    async def reply(self, aseco, player, text):
        await aseco.client.query_ignore_result('ChatSendServerMessageToLogin',
            aseco.format_colors('{#server}> ' + text), player.login)

    async def confirm(self, aseco, player, action, arguments):
        if not arguments:
            token = secrets.token_hex(3)
            self.pending[player.login] = (action, token, monotonic() + 120,
                                           self.data['revision'], self.data['match_id'])
            await self.reply(aseco, player, f'Confirm within 120s: //tmatch {action} confirm {token}')
            return False
        pending = self.pending.pop(player.login, None)
        if (len(arguments) != 2 or arguments[0].lower() != 'confirm' or pending is None or
                pending[0] != action or not secrets.compare_digest(pending[1], arguments[1]) or
                monotonic() > pending[2] or pending[3:] != (self.data['revision'], self.data['match_id'])):
            raise ValueError('Confirmation expired or match changed. Request the action again.')
        return True

    async def command(self, aseco, player, args):
        if not (aseco.is_master_admin(player) or aseco.is_admin(player)):
            await self.reply(aseco, player, '{#error}Only Admins and MasterAdmins may manage FAST matches.')
            return
        action = args[0].lower() if args else 'help'
        try:
            if action == 'help':
                await self.reply(aseco, player, '//tmatch start|status|pause|resume|stop; score <blue> <red>; '
                    'team <blue|red> <name>; export [txt|html]; undo; reset.')
                return
            if action == 'export' and len(args) <= 2:
                state = self.snapshot(details=True)
                if state is None:
                    raise ValueError('No saved match is available to export.')
                try:
                    name = await file_io(reports.write_report, self.path.parent / 'exports', state,
                                         args[1].lower() if len(args) == 2 else 'txt')
                except OSError:
                    raise ValueError('Cannot write the FAST match report.') from None
                await self.reply(aseco, player, 'Report saved on server: apps/ui_fast/exports/' + name)
                return
            if action == 'status':
                state = self.snapshot()
                if state is None:
                    await self.reply(aseco, player, 'FAST match: ' + (self.error or 'no match / feature disabled.'))
                else:
                    state_label = ('complete' if state['state'] == 'stopped' and state['target_reached']
                                   else state['state'])
                    await self.reply(aseco, player, f'FAST match {state_label}: {state["names"][0]} '
                        f'{state["totals"][0]} - {state["totals"][1]} {state["names"][1]}; '
                        f'{state["counted"]} maps. ' + ('Current map eligible.' if self.attempt else 'Current map excluded.')
                        + (' Needs attention: ' + self.error if self.error else ''))
                    for row in [row for row in state['maps'] if not row['void']][-5:]:
                        await self.reply(aseco, player, f'{row["name"]}$z: {row["scores"][0]} - {row["scores"][1]}')
                return
            if not self.enabled:
                raise ValueError('Enable ui_fast.competition.enabled in //apps config ui_fast first.')
            if self.error and action != 'reset':
                raise ValueError('FAST match state needs attention: ' + self.error)
            if action == 'start' and len(args) == 1:
                if self.data['match_id']:
                    raise ValueError('A saved match already exists; resume it or reset it first.')
                data = empty_state()
                data.update(match_id=uuid4().hex, server_login=aseco.server.serverlogin,
                            state='armed', names=list(self.default_names), rules=dict(self.default_rules))
                self.attempt = None
                await self.commit(data)
            elif action in ('pause', 'resume', 'stop') and len(args) == 1:
                self.require_admin(aseco, player)
                if action == 'resume' and self.data['state'] not in ('paused', 'stopped'):
                    raise ValueError('Match is already collecting or waiting for a fresh map.')
                if action == 'resume' and reached_target(self.data):
                    raise ValueError('The match target is already reached. Adjust totals or start a new match.')
                data = deepcopy(self.data)
                data['state'] = {'pause': 'paused', 'resume': 'armed', 'stop': 'stopped'}[action]
                self.attempt = None
                await self.commit(data)
            elif action == 'score' and len(args) == 3:
                await self.set_score(aseco, player, [int(value) for value in args[1:]])
                await self.reply(aseco, player, 'Overall match score corrected; native map scores unchanged.')
                return
            elif action == 'team' and len(args) >= 3 and args[1].lower() in ('blue', 'red'):
                await self.set_name(aseco, player, 0 if args[1].lower() == 'blue' else 1, ' '.join(args[2:]))
                await self.reply(aseco, player, 'Match team name updated.')
                return
            elif action in ('undo', 'reset'):
                if action == 'undo':
                    self.require_admin(aseco, player)
                    if not any(not row['void'] for row in self.data['maps']):
                        raise ValueError('No counted map to undo.')
                if not await self.confirm(aseco, player, action, args[1:]):
                    return
                if action == 'reset':
                    data = empty_state()
                    self.attempt = None
                else:
                    data = deepcopy(self.data)
                    row = next(row for row in reversed(data['maps']) if not row['void'])
                    row['void'] = True
                    if any(score < 0 for score in totals(data)):
                        raise ValueError('Undo would make totals negative after a manual correction. Correct totals first.')
                    data['adjustments'].append(dict(action='undo', actor=player.login, at=timestamp(), map_id=row['id']))
                await self.commit(data)
                self.error = ''
            else:
                raise ValueError('Unknown command or invalid arguments. Use //tmatch help.')
            await self.notify(aseco)
            await self.reply(aseco, player, 'FAST match updated. Start/resume waits for the next fresh map. '
                                           'Use //tmatch status to review.')
        except ValueError as error:
            await self.reply(aseco, player, '{#error}' + str(error))

    async def disconnect(self, aseco, player):
        self.pending.pop(player.login, None)
        self.rounds.disconnect(aseco, player)

    async def shutdown(self, aseco):
        self.attempt = None
        self.rounds.reset()
        if self.ready and not self.error and self.data['state'] in ('armed', 'running'):
            data = deepcopy(self.data)
            data['state'] = 'paused'
            await self.commit(data)
        self.enabled = False
        self.pending.clear()
        await self.notify(aseco)
