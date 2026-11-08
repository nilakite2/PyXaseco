"""Read existing record snapshots; never fetch or import an optional provider."""

from dataclasses import dataclass
import sys

from pyxaseco.app_services import get_dedi_db
from pyxaseco.models import Gameinfo


@dataclass(frozen=True)
class Source:
    key: str
    title: str
    command: str
    rows: tuple


def normalise(rows):
    result = []
    for position, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            continue
        try:
            score = int(row.get('score') or row.get('best_score') or row.get('Best') or 0)
            rank = int(row.get('rank') or row.get('Pos') or position)
        except (TypeError, ValueError):
            continue
        if score <= 0 or rank <= 0:
            continue
        login = str(row.get('login') or row.get('Login') or '')
        nickname = next((str(row[key]) for key in (
            'player_nickname_raw', 'nickname_raw', 'nickname', 'player_nickname', 'NickName',
            'Nickname', 'tmx_name', 'TmxName') if row.get(key)), login or '?')
        checks = row.get('checks') or row.get('Checks') or row.get('checkpointsMs') or []
        result.append(dict(rank=rank, score=score, login=login, nickname=nickname, checks=checks))
    return tuple(result)


async def snapshots(aseco):
    from apps.ui.config import _effective_mode

    active = set(getattr(aseco, 'active_apps', ()) or ())
    uid = str(getattr(aseco.server.challenge, 'uid', '') or '')
    mode = _effective_mode(aseco)
    sources = []
    # Prefer specialised lists initially, but keep every available source selectable.
    if mode != Gameinfo.STNT:
        for app, label, command in (('records_trial', 'Trial Records', '/trialrecs'),
                                    ('records_rpg', 'RPG Records', '/rpgrecs')):
            module = sys.modules.get(f'apps.{app}.service') if app in active else None
            if module is None or not module.is_enabled():
                continue
            track = module.get_current_track_cache()
            if not track or uid not in module._track_all_uids(track):
                continue
            # Both current-record accessors are cache-only once the UID matches.
            accessor = getattr(module, 'get_current_trial_records' if app == 'records_trial'
                               else 'get_current_rpg_records')
            sources.append(Source(app, label, command, normalise(await accessor(aseco))))
        module = sys.modules.get('apps.records_dedimania.service')
        data = get_dedi_db(aseco) if 'records_dedimania' in active else {}
        if module is not None and getattr(module, '_connected', False) and data.get('RecsValid'):
            sources.append(Source('records_dedimania', 'Dedimania', '/dedirecs',
                                  normalise(data.get('Challenge', {}).get('Records', []))))
    local = []
    for rank, record in enumerate(aseco.server.records, 1):
        player = record.player
        local.append(dict(rank=rank, score=record.score,
                          login=getattr(player, 'login', ''),
                          nickname=getattr(player, 'nickname', '?'),
                          checks=getattr(record, 'checks', [])))
    sources.append(Source('records_local', 'Local Records', '/recs', normalise(local)))
    for app, label, command in (('records_ultimania', 'Ultimania', '/ultirecs'),
                                ('records_wrmania', 'Mania Records', '/wrrecs')):
        service = aseco.get_service(f'service/{app}') if app in active else None
        if service is not None and service.active(aseco):
            limit = getattr(getattr(service, 'client', None), 'limit', len(service.rows))
            rows = normalise(service.rows)
            sources.append(Source(app, label, command, tuple(row for row in rows if row['rank'] <= limit)))
    return sources


def nearby(rows, login, entries, topcount):
    """Pin leaders, then the player's neighbourhood without blank filler rows."""
    if len(rows) <= entries:
        return rows
    leaders = list(rows[:topcount])
    position = next((index for index, row in enumerate(rows) if row['login'] == login), 0)
    slots = entries - len(leaders)
    start = max(len(leaders), position - slots // 2)
    start = min(start, len(rows) - slots)
    return tuple(leaders + list(rows[start:start + slots]))
