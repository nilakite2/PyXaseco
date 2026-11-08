"""Observe native Team rounds; projected points never affect dedicated scoring."""

from pyxaseco.models import Gameinfo


def racing(player):
    return (not getattr(player, 'isspectator', False)
            and not int(getattr(player, 'spectatorstatus', 0) or 0) % 10
            and type(getattr(player, 'teamid', None)) is int and player.teamid in (0, 1))


class TeamRounds:
    def __init__(self):
        self.reset()

    def reset(self):
        self.generation = None
        self.roster = {}
        self.progress = {}
        self.cap = None
        self.number = 0
        self.open = False
        self.last = None
        self._projection = None

    def begin(self, aseco):
        if self.generation != aseco._map_generation:
            self.reset()
            self.generation = aseco._map_generation
        self.number += 1
        self.roster = {p.login: (p.nickname[:120], p.teamid) for p in aseco.server.players.all() if racing(p)}
        self.progress.clear()
        if len(self.roster) > 256:
            self.open = False
            self.last = self._projection = None
            return
        cap = aseco.server.gameinfo.raw.get('TeamMaxPoints')
        self.cap = cap if type(cap) is int and cap >= 0 else None
        self.open = True
        self._projection = None

    def current(self, aseco):
        return (self.open and self.generation == aseco._map_generation
                and aseco.server.gameinfo.mode == Gameinfo.TEAM and not aseco.warmup_phase)

    def checkpoint(self, aseco, data):
        if not self.current(aseco) or len(data) < 5:
            return
        login, elapsed, index = data[1], data[2], data[4]
        if (login not in self.roster or type(elapsed) is not int or elapsed <= 0
                or type(index) is not int or index < 0):
            return
        previous = self.progress.get(login)
        if previous and (previous[0] != 'racing' or index <= previous[1] or elapsed <= previous[2]):
            return
        self.progress[login] = ('racing', index, elapsed)
        self._projection = None

    def finish(self, aseco, record):
        if not self.current(aseco) or record.player.login not in self.roster:
            return
        login = record.player.login
        if record.score <= 0:
            self.retire(aseco, login)
        elif self.progress.get(login, ('',))[0] not in ('finished', 'dnf'):
            self.progress[login] = ('finished', -1, int(record.score))
            self._projection = None

    def retire(self, aseco, login):
        if self.current(aseco) and login in self.roster:
            previous = self.progress.get(login, ('racing', -1, 0))
            if previous[0] == 'racing':
                self.progress[login] = ('dnf', previous[1], previous[2])
                self._projection = None

    def info(self, aseco, player):
        if not self.current(aseco):
            return
        entry = self.roster.get(player.login)
        if (entry and (player.teamid != entry[1] or not racing(player))) or (not entry and racing(player)):
            # A mid-round roster change makes the original points basis unreliable.
            self.cap = None
            self._projection = None
        if not racing(player):
            self.retire(aseco, player.login)

    def disconnect(self, aseco, player):
        if self.current(aseco) and player.login in self.roster:
            self.cap = None
            self._projection = None
            self.retire(aseco, player.login)

    def model(self, *, final=False):
        ranked = sorted(
            ((login, *point) for login, point in self.progress.items()
             if point[0] == 'finished' or (not final and point[0] == 'racing')),
            key=lambda row: (row[1] != 'finished', -row[2], row[3], row[0]),
        )
        sums = [0, 0] if self.cap is not None else None
        members = [sum(team == i for _, team in self.roster.values()) for i in (0, 1)]
        equal_size = min(members)
        team_ranks = [0, 0]
        rows = []
        for rank, (login, state, index, elapsed) in enumerate(ranked, 1):
            nickname, team = self.roster[login]
            team_ranks[team] += 1
            points = None
            if sums is not None:
                if self.cap:
                    points = max(0, min(self.cap, len(self.roster)) - rank + 1)
                elif team_ranks[team] <= equal_size:
                    points = equal_size * 2 + 1 - min(rank, team_ranks[team] + equal_size)
                else:
                    points = 0
                sums[team] += points
            rows.append(dict(login=login, name=nickname, team=team, state=state, rank=rank,
                             checkpoint=index + 1 if index >= 0 else None, time_ms=elapsed, points=points))
        if final:
            for login, (nickname, team) in self.roster.items():
                point = self.progress.get(login)
                if point and point[0] == 'finished':
                    continue
                index, elapsed = point[1:] if point else (-1, 0)
                rows.append(dict(login=login, name=nickname, team=team, state='dnf', rank=None,
                                 checkpoint=index + 1 if index >= 0 else None,
                                 time_ms=elapsed or None, points=0 if sums is not None else None))
        return dict(number=self.number, final=final, points=sums, players=rows)

    def snapshot(self):
        if not self.open:
            return self.last
        if self._projection is None:
            self._projection = self.model()
        return self._projection

    def end(self, aseco):
        if not self.current(aseco):
            return None
        self.open = False
        self.last = self.model(final=True) if self.roster else None
        return self.last
