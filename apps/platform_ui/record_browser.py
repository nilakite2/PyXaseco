"""Shared leaderboard and split navigation. Providers own record retrieval."""

from dataclasses import dataclass, replace
from itertools import count

from pyxaseco.core.background_jobs import Admission, JobEnvelope, JobPolicy
from pyxaseco.core.widget_delivery import is_score_phase
from pyxaseco.helpers import format_time, strip_colors
from .windows import send_page


_ids = count(441000000)
_icon = ['BgRaceScore2', 'Podium']
_rows = 12


@dataclass(frozen=True)
class Run:
    login: str
    name: str
    score: int
    rank: int | None = None
    splits: tuple = ()


def split_values(values):
    if isinstance(values, str):
        values = values.split(',')
    if not isinstance(values, (list, tuple)):
        return ()
    clean = []
    for value in values[:5000]:
        try:
            value = int(value) if not isinstance(value, bool) else 0
        except (TypeError, ValueError, OverflowError):
            value = 0
        clean.append(value if value > 0 else None)
    return tuple(clean) if any(clean) else ()


def _map(aseco):
    return (getattr(aseco, '_map_generation', None), getattr(aseco.server.challenge, 'uid', None))


class Browser:
    def __init__(self, aseco, player, title, runs, *, pb=None, fetch=None, valid=None, show_logins=False):
        self.aseco, self.player = aseco, player
        self.title, self.runs, self.pb, self.fetch = title, tuple(runs), pb, fetch
        self.valid_provider = valid
        self.show_logins = show_logins
        self.map = _map(aseco)
        self.stunts = getattr(aseco.server.gameinfo, 'mode', 0) == 4
        self.board_page = 1
        self.actions = {}
        self.window = None
        self.kind = ''
        self.selected = None
        self.waiting = False
        self.closed = False

    def valid(self, aseco, player):
        return (self.map == _map(aseco) and player is self.player
                and aseco.server.players.get_player(player.login) is player
                and getattr(player, '_record_browser', None) is self)

    def action(self, label, func, *args):
        action = next(_ids)
        self.actions[action] = (func, args)
        return [label, action]

    async def render(self, title, widths, pages, *, page=1):
        self.window = [[page, title, widths, _icon, self.valid], *pages]
        self.player.msgs = self.window
        await send_page(self.aseco, self.player)

    def time(self, value):
        return '--' if value is None else str(value) if self.stunts else format_time(value)

    def can_compare(self, run):
        if self.stunts or not self.aseco.get_service('ui/compare_run') or not run.splits:
            return False
        expected = getattr(self.aseco.server.challenge, 'nbchecks', 0) or 0
        return ((not expected or len(run.splits) == expected) and run.splits[-1] == run.score
                and all(run.splits) and all(a < b for a, b in zip(run.splits, run.splits[1:])))

    async def board(self):
        self.actions.clear()
        self.kind = 'board'
        self.selected = None
        mine = self.action('My PB', self.personal)
        nick_colors = getattr(self.aseco.settings, 'lists_colornicks', False)
        widths = [1.22, .11, .43, .42, .26] if self.show_logins else [1.05, .11, .66, .28]
        heading = ['Rank', 'Player (select)', 'Login', 'Time'] if self.show_logins else ['Rank', 'Player (select)', 'Time']
        rows = []
        for run in self.runs:
            nick = run.name if nick_colors else strip_colors(run.name)
            columns = [f'{run.rank}.', self.action(nick or run.login, self.card, run)]
            if self.show_logins:
                columns.append(run.login)
            rows.append([*columns, self.time(run.score)])
        pages = [[['', mine, ''], heading] + rows[i:i + _rows]
                 for i in range(0, len(rows), _rows)]
        await self.render(self.title, widths, pages or [[['No records on this map.'], ['', mine, '']]], page=self.board_page)

    async def reply(self, message):
        await self.aseco.client.query_ignore_result('ChatSendServerMessageToLogin',
            self.aseco.format_colors('{#server}> ' + message), self.player.login)

    async def personal(self):
        run = next((item for item in self.runs if item.login == self.player.login), None)
        if run is not None:
            await self.card(run)
        elif self.pb:
            viewer = self.player
            await self.lookup(self.pb, (viewer.login, viewer.id, viewer.nickname), self.card)
        else:
            await self.reply('No personal best in the records supplied by this provider.')

    async def lookup(self, fetch, args, complete):
        if self.waiting:
            return
        aseco, player = self.aseco, self.player
        origin = self.window
        self.waiting = True

        async def operation(_envelope):
            return await fetch(*args)

        async def done(result):
            self.waiting = False
            if self.closed or not self.valid(aseco, player) or player.msgs is not origin or self.window is not origin:
                return
            if (result.status != 'completed'
                    or (self.valid_provider and not self.valid_provider(aseco, player))):
                await self.reply('Record or checkpoint provider unavailable; try again later.')
            elif result.value is None:
                await self.reply('No saved personal best on this map.')
            else:
                await complete(result.value)

        ticket = JobEnvelope.capture(aseco.capture_job_context(login=player.login), {})

        async def discarded(_result):
            self.waiting = False

        result = aseco.jobs.service('record_browser', JobPolicy(deadline_seconds=30)).submit(
            ticket, operation, done, dedupe_key=f'{id(self)}', discard=discarded)
        if result != Admission.ACCEPTED:
            self.waiting = False
            await self.reply('Record lookup is busy; try again shortly.')
        else:
            await self.reply('Loading saved record data...')

    async def card(self, run):
        if self.kind == 'board':
            self.board_page = self.window[0][0]
        self.kind, self.selected = 'card', run
        self.actions.clear()
        rows = [['Record', self.time(run.score), f'Rank {run.rank}' if run.rank else 'Outside shown ranks'],
                ['Player', run.login, self.action('Back to records', self.board)]]
        if self.stunts:
            rows.append(['Timed splits are unavailable in Stunts.'])
        elif run.splits or self.fetch:
            rows.append(['Saved splits', self.action('Checkpoint times', self.open_splits, False),
                         self.action('Sector times', self.open_splits, True)])
        else:
            rows.append(['No splits saved for this record.'])
        if self.can_compare(run):
            rows.append(['Live delta', self.action('Compare against this run', self.compare), ''])
        await self.render(self.title + ' | ' + strip_colors(run.name)[:42], [1.18, .26, .47, .45], [rows])

    async def compare(self):
        if is_score_phase(self.aseco):
            await self.reply('Start a comparison during the race.')
            return
        compare = self.aseco.get_service('ui/compare_run')
        if compare:
            await compare(self.aseco, self.player, self.selected, self.title)

    async def open_splits(self, sectors):
        run = self.selected
        if not run.splits and self.fetch:
            async def complete(splits):
                await self.splits(replace(run, splits=split_values(splits)), sectors)
            await self.lookup(self.fetch, (run,), complete)
        else:
            await self.splits(run, sectors)

    async def splits(self, run, sectors):
        self.kind, self.selected = 'splits', run
        self.actions.clear()
        back = self.action('Back to record', self.card, run)
        toggle = self.action('Checkpoint times' if sectors else 'Sector times', self.splits, run, not sectors)
        title = ('Sector times' if sectors else 'Checkpoint times') + ' | ' + strip_colors(run.name)[:32]
        compare_cell = self.action('Compare against this run', self.compare) if self.can_compare(run) else ''
        pages = []
        for start in range(0, len(run.splits), _rows):
            end = min(start + _rows, len(run.splits))
            rows = [[f'Splits {start + 1}-{end} / {len(run.splits)}', toggle, back],
                    ['Split', 'Sector' if sectors else 'Elapsed', '/recordcp <number> jumps pages']]
            if compare_cell:
                rows.insert(1, ['', compare_cell, ''])
            for index in range(start, end):
                time = run.splits[index]
                finish = index == len(run.splits) - 1 and time == run.score
                if sectors:
                    previous = run.splits[index - 1] if index else 0
                    time = time - previous if time is not None and previous is not None and time >= previous else None
                rows.append(['Finish' if finish else f'CP {index + 1}', self.time(time), ''])
            pages.append(rows)
        await self.render(title, [1.16, .28, .39, .49],
                          pages or [[['No saved splits match this record.', '', back]]])


async def show(aseco, player, title, runs, **options):
    browser = Browser(aseco, player, title, runs, **options)
    player._record_browser = browser
    await browser.board()


def _current(aseco, player, *, allow_closed=False):
    browser = getattr(player, '_record_browser', None)
    if (browser and browser.valid(aseco, player) and browser.window is player.msgs
            and (allow_closed or not browser.closed)):
        return browser
    return None


def reopen(aseco, player):
    browser = _current(aseco, player, allow_closed=True)
    if browser:
        browser.closed = False


async def _answer(aseco, answer):
    if len(answer) < 3:
        return
    try:
        action = int(answer[2])
    except (ValueError, TypeError):
        return
    player = aseco.server.players.get_player(answer[1])
    if not player:
        return
    browser = _current(aseco, player)
    if action == 0 and browser:
        browser.closed = True
        return
    if not browser or action not in browser.actions:
        return
    if browser.valid_provider and not browser.valid_provider(aseco, player):
        await browser.reply('Record provider unavailable; reopen the leaderboard.')
        return
    func, args = browser.actions[action]
    await func(*args)


async def _jump(aseco, command):
    player = command['author']
    browser = _current(aseco, player)
    value = str(command.get('params') or '').strip()
    if browser and browser.valid_provider and not browser.valid_provider(aseco, player):
        await browser.reply('Record provider unavailable; reopen the leaderboard.')
        return
    if (browser and browser.kind == 'splits' and value.isascii() and value.isdecimal()
            and len(value) <= 5 and 1 <= int(value) <= len(browser.selected.splits)):
        browser.window[0][0] = (int(value) - 1) // _rows + 1
        await send_page(aseco, player)
        return
    text = 'Open a record\'s splits first, then use /recordcp <number>.'
    if browser and browser.kind == 'splits' and browser.selected.splits:
        text = f'Use /recordcp <number> within 1-{len(browser.selected.splits)}.'
    await aseco.client.query_ignore_result('ChatSendServerMessageToLogin', aseco.format_colors(text), player.login)


def register(aseco):
    aseco.register_event('onPlayerManialinkPageAnswer', _answer)
    aseco.register_event('onChat_recordcp', _jump)
    aseco.add_chat_command('recordcp', 'Jump to a numbered split in the current record window',
                           app='platform_ui', usage='/recordcp <number>')
