"""Live split presentation. Core owns checkpoint arrays and record validation."""

from dataclasses import dataclass

from pyxaseco.models import Gameinfo
from apps.platform_core.checkpoints import checkpoints


MODES = ('best', 'ideal', 'reference')


def complete_checks(values, score, count):
    if isinstance(values, str):
        values = values.split(',')
    if not isinstance(values, (tuple, list)) or not 0 < len(values) <= 100000:
        return ()
    try:
        if any(isinstance(value, bool) for value in values):
            return ()
        checks = tuple(int(value) for value in values)
        if (checks[0] <= 0 or checks[-1] != int(score) or
                any(a >= b for a, b in zip(checks, checks[1:])) or
                (count > 0 and len(checks) != count)):
            return ()
    except (TypeError, ValueError, OverflowError):
        return ()
    return checks


def personal_best(aseco, login):
    count = int(getattr(aseco.server.challenge, 'nbchecks', 0) or 0)
    candidates = []
    for record in aseco.server.records:
        if getattr(getattr(record, 'player', None), 'login', '') == login:
            checks = complete_checks(getattr(record, 'checks', ()), record.score, count)
            if checks:
                candidates.append((int(record.score), checks))
    cp = checkpoints.get(login)
    # A positive loclrec can contain someone else's selected record, not this
    # player's session PB. Never relabel that record as a personal best.
    if cp is not None and cp.loclrec <= 0:
        checks = complete_checks(cp.best_cps, cp.best_fin, count)
        if checks:
            candidates.append((int(cp.best_fin), checks))
    return min(candidates, default=(0, ()), key=lambda item: item[0])[1]


@dataclass(frozen=True)
class Point:
    index: int
    absolute: int
    time: int | None
    next_base: int | None
    personal: tuple
    finished: bool = False


class LiveSplits:
    def __init__(self):
        self.points = {}
        self.baselines = {}
        self.split_times = {}
        self.best = ()
        self.ideal = ()

    def reset(self):
        self.points.clear()
        self.baselines.clear()
        self.split_times.clear()
        self.best = self.ideal = ()

    def round_start(self):
        self.points.clear()
        self.baselines.clear()
        self.split_times.clear()

    def discard(self, login):
        self.points.pop(login, None)
        self.baselines.pop(login, None)
        self.split_times.pop(login, None)

    def save_time(self, login, index, absolute, *, fresh=False):
        if fresh:
            self.split_times.pop(login, None)
        times = self.split_times.setdefault(login, {})
        times[index] = absolute
        if len(times) > 64:
            times.pop(next(iter(times)))

    def update_references(self, aseco, sources):
        count = int(getattr(aseco.server.challenge, 'nbchecks', 0) or 0)
        arrays = [checks for source in sources for row in source.rows
                  if (checks := complete_checks(row.get('checks'), row['score'], count))]
        for cp in checkpoints.values():
            checks = complete_checks(cp.best_cps, cp.best_fin, count)
            if checks:
                arrays.append(checks)
        self.best = min(arrays, key=lambda checks: checks[-1], default=())
        self.ideal = ()
        if arrays:
            # Only combine like-for-like, complete runs of the current map.
            length = len(self.best)
            arrays = [checks for checks in arrays if len(checks) == length]
            sectors = [min(checks[i] - (checks[i - 1] if i else 0) for checks in arrays)
                       for i in range(length)]
            cumulative = []
            for sector in sectors:
                cumulative.append((cumulative[-1] if cumulative else 0) + sector)
            self.ideal = tuple(cumulative)

    def checkpoint(self, aseco, data):
        if not isinstance(data, (list, tuple)) or len(data) < 5:
            return None
        try:
            login, absolute, index = str(data[1]), int(data[2]), int(data[4])
        except (TypeError, ValueError, OverflowError):
            return None
        if absolute <= 0 or index < 0 or aseco.server.players.get_player(login) is None:
            return None
        previous = self.points.get(login)
        count = int(getattr(aseco.server.challenge, 'nbchecks', 0) or 0)
        laps = aseco.server.gameinfo.mode == Gameinfo.LAPS and count > 0
        if (not laps and count > 0 and index >= count) or (previous is not None and index != 0 and
                (index <= previous.index or absolute <= previous.absolute)):
            return None
        if index == 0 or previous is None or (laps and index % count == 0):
            self.baselines[login] = personal_best(aseco, login)
        personal = self.baselines.get(login, ())
        base = 0
        if laps:
            if index == 0:
                base = 0
            elif previous is not None and index == previous.index + 1 and absolute > previous.absolute:
                base = previous.next_base
            else:
                cp = checkpoints.get(login)
                end = getattr(cp, 'curr_fin', None)
                # At lap end core has already replaced curr_fin. Without a
                # known previous base, withhold the delta instead of guessing.
                base = end if isinstance(end, int) and 0 <= end < absolute else None
        time = absolute - base if base is not None else None
        next_base = absolute if laps and (index + 1) % count == 0 else base
        finished = not laps and count > 0 and index + 1 == count
        point = Point(index, absolute, time, next_base, personal, finished)
        self.points[login] = point
        self.save_time(login, index, absolute, fresh=index == 0)
        return login

    def finish(self, aseco, record):
        player, score = getattr(record, 'player', None), getattr(record, 'score', 0)
        if player is None:
            return None
        login = player.login
        if score <= 0:
            self.discard(login)
        elif aseco.server.gameinfo.mode != Gameinfo.LAPS:
            count = int(getattr(aseco.server.challenge, 'nbchecks', 0) or 0)
            previous = self.points.get(login)
            personal = previous.personal if previous else self.baselines.get(login, ())
            self.points[login] = Point(max(0, count - 1), int(score), int(score), 0, personal, True)
            if count > 0:
                self.save_time(login, count - 1, int(score))
        return login

    def race_order(self, aseco):
        # TA attempts do not start together; PB standings are not a live race.
        if aseco.server.gameinfo.mode not in (Gameinfo.RNDS, Gameinfo.TEAM, Gameinfo.LAPS, Gameinfo.CUP):
            return [], 0
        runners = [player for player in aseco.server.players.all()
                   if not getattr(player, 'isspectator', False) and not getattr(player, 'retired', False)
                   and not int(getattr(player, 'spectatorstatus', 0) or 0) % 10]
        seen = [player for player in runners if player.login in self.points]
        seen.sort(key=lambda player: (*self.race_key(player.login), player.login))
        return seen, len(runners)

    def race_key(self, login):
        point = self.points[login]
        return not point.finished, -point.index, point.absolute

    def position(self, aseco, login):
        runners, total = self.race_order(aseco)
        if any(player.login == login for player in runners):
            own = self.race_key(login)
            return 1 + sum(self.race_key(player.login) < own for player in runners), total
        return None

    def gaps(self, aseco, login, runners):
        position = next((index for index, player in enumerate(runners) if player.login == login), None)
        if position is None:
            return []
        own = self.points[login]
        neighbors = []
        if position > 1:
            neighbors.append(('Leader', runners[0]))
        if position > 0:
            neighbors.append(('Leader' if position == 1 else 'Ahead', runners[position - 1]))
        if position + 1 < len(runners):
            neighbors.append(('Behind', runners[position + 1]))
        result = []
        count = int(getattr(aseco.server.challenge, 'nbchecks', 0) or 0)
        for label, player in neighbors:
            other = self.points[player.login]
            shared = min(own.index, other.index)
            mine = self.split_times.get(login, {}).get(shared)
            theirs = self.split_times.get(player.login, {}).get(shared)
            checkpoint = ('Finish' if count > 0 and shared == count - 1 and
                          aseco.server.gameinfo.mode != Gameinfo.LAPS else f'CP {shared + 1}')
            result.append(dict(label=label, name=player.nickname, progress=other.index - own.index,
                               delta=mine - theirs if mine is not None and theirs is not None else None,
                               checkpoint=checkpoint))
        return result

    def model(self, aseco, login, mode, source, reference_rank, show_position, show_gaps=False, race=None):
        point = self.points.get(login)
        if point is None:
            return None
        count = int(getattr(aseco.server.challenge, 'nbchecks', 0) or 0)
        laps = aseco.server.gameinfo.mode == Gameinfo.LAPS and count > 0
        index = point.index % count if laps else point.index
        reference = self.best if mode == 'best' else self.ideal
        title = mode.capitalize()
        if mode == 'reference':
            row = next((row for row in source.rows if row['rank'] == reference_rank), None)
            reference = complete_checks(row.get('checks'), row['score'], count) if row else ()
            title = f'{source.title} #{reference_rank}'
        def delta(checks):
            return point.time - checks[index] if point.time is not None and index < len(checks) else None
        # TMF includes the finish split in nbchecks and record arrays, not just CPs.
        total = max(0, count - 1)
        finished = point.finished or (laps and index + 1 == count)
        runners, players = (race if race is not None else self.race_order(aseco)) if show_position or show_gaps else ([], 0)
        position = None
        if show_position and any(player.login == login for player in runners):
            position = 1 + sum(self.race_key(player.login) < self.race_key(login) for player in runners), players
        return dict(cp=min(index + 1, total) if count > 0 else index + 1, total=total,
                    time=point.time, personal=delta(point.personal),
                    comparison=delta(reference), title=title, finished=finished,
                    lap=point.index // count + 1 if laps else None,
                    position=position, gaps=self.gaps(aseco, login, runners) if show_gaps else [])
