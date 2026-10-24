"""Read-only result snapshots; no changes to records, points or ladder awards."""

from time import time


MAX_PLAYERS = 300
MODES = {0: 'Rounds', 1: 'Time Attack', 2: 'Team', 3: 'Laps', 4: 'Stunts', 5: 'Cup'}


def number(value, default=0):
    try:
        return int(value or 0)
    except (ValueError, TypeError):
        return default


def spectator(player):
    return bool(getattr(player, 'isspectator', False) or number(getattr(player, 'spectatorstatus', 0)) % 10)


def better(first, second, mode):
    scores = [number(value) for value in (first, second) if number(value) > 0]
    return (max(scores) if mode == 4 else min(scores)) if scores else 0


def player_data(player):
    return {'login': str(player.login)[:75], 'name': str(getattr(player, 'nickname', '') or player.login)[:160],
            'id': number(getattr(player, 'id', 0)), 'spectator': spectator(player), 'connected': True,
            'team': number(getattr(player, 'teamid', -1), -1),
            'ladder': number(getattr(player, 'ladderrank', 0)),
            'nation': str(getattr(player, 'nation', '') or '-')[:80],
            'created': number(getattr(player, 'created', 0)), 'finishes': 0, 'best': 0}


async def personal_bests(pool, challenge_id, players, mode):
    """Two bounded queries, including legacy rs_times-only personal bests."""
    ids = tuple(dict.fromkeys(row['id'] for row in players if row['id'] > 0))
    if pool is None or not challenge_id or not ids:
        return {}, False
    aggregate = 'MAX' if mode == 4 else 'MIN'
    marks = ','.join(['%s'] * len(ids))
    found, available = {}, False
    async with pool.acquire() as connection:
        async with connection.cursor() as cursor:
            for table in ('records', 'rs_times'):
                # Both tables use these case-insensitive column identifiers in the existing schema.
                try:
                    await cursor.execute(f'SELECT PlayerId, {aggregate}(Score) FROM {table} '
                        f'WHERE ChallengeId=%s AND PlayerId IN ({marks}) AND Score>0 GROUP BY PlayerId',
                        (challenge_id, *ids))
                    for player_id, score in await cursor.fetchall():
                        found[number(player_id)] = better(found.get(number(player_id), 0), score, mode)
                    available = True
                except Exception:
                    # The legacy times table may not exist; retain any successfully read PBs.
                    continue
    return found, available


def build(payload, rankings, pbs, pb_available):
    mode = payload['mode']
    metadata = {row['login']: dict(row) for row in payload['players']}
    teams, ordered = {}, []
    for index, raw in enumerate(rankings[:MAX_PLAYERS]):
        if not isinstance(raw, dict):
            continue
        login = str(raw.get('Login') or '')[:75]
        if mode == 2:
            team = number(raw.get('TeamId', index), index)
            if team in (0, 1):
                teams[team] = max(0, number(raw.get('Score')))
            continue
        if not login or any(row['login'] == login for row in ordered):
            continue
        row = metadata.pop(login, {'login': login, 'name': str(raw.get('NickName') or login)[:160],
            'id': 0, 'spectator': False, 'connected': False, 'team': -1, 'ladder': 0,
            'nation': '-', 'created': 0, 'finishes': 0, 'best': 0})
        row.update(rank=max(0, number(raw.get('Rank'))), score=max(0, number(raw.get('Score'))),
                   time=max(0, number(raw.get('BestTime'))))
        ordered.append(row)
    for row in metadata.values():
        row.update(rank=0, score=row['best'] if mode == 4 else 0, time=row['best'] if mode != 4 else 0)
        ordered.append(row)
    if mode == 2:
        ordered.sort(key=lambda row: (row['team'] not in (0, 1), row['team'], row['spectator'],
                                     row['time'] <= 0, row['time'], row['login']))
    else:
        ordered.sort(key=lambda row: (row['rank'] <= 0, row['rank'] or MAX_PLAYERS + 1, row['login']))
    for row in ordered:
        row['pb'] = better(pbs.get(row['id'], 0), payload['local_pbs'].get(row['login'], 0), mode)
        row['pb'] = better(row['pb'], row['best'], mode)
        row['online'] = max(0, int(time()) - row['created']) if row['created'] and row['connected'] else 0
        if not row['time'] and not row['score']:
            row['rank'] = 0
    return {'mode': mode, 'map': payload['map'], 'rows': ordered[:MAX_PLAYERS], 'teams': teams,
            'pb_available': pb_available, 'players': sum(not row['spectator'] and row['connected'] for row in ordered),
            'spectators': sum(row['spectator'] and row['connected'] for row in ordered)}
