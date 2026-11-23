"""Feed a bounded TMX ID file into the existing download queue, one map at a time."""

from collections import deque
from dataclasses import dataclass
import logging
from pathlib import Path, PureWindowsPath
import re
import time
from xml.etree.ElementTree import ParseError

from pyxaseco.core.background_jobs import Admission
from pyxaseco.core.file_io import file_io

from . import matchsettings


logger = logging.getLogger(__name__)
IMPORT_DIR = 'map_imports'
MAX_BYTES = 32 * 1024
MAX_IDS = 500
QUEUE_WAIT = 120.0


@dataclass
class ImportBatch:
    admin: object
    preset: str
    settings_path: Path
    section: str
    remaining: deque[int]
    skipped: int = 0
    added: int = 0
    rejected: int = 0
    inflight: bool = False
    stop: str = ''
    retry_at: float = 0.0
    waiting_since: float | None = None


def read_ids(root: Path, filename: str) -> tuple[deque[int], int]:
    if (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}\.txt', filename, re.IGNORECASE)
            or PureWindowsPath(filename).is_reserved()):
        raise ValueError('Use a simple .txt filename inside map_imports.')
    folder = root.resolve() / IMPORT_DIR
    path = folder / filename
    if (folder.is_symlink() or folder.is_junction() or not folder.is_dir()
            or path.is_symlink() or path.resolve().parent != folder or not path.is_file()):
        raise ValueError('Place a regular .txt file inside the controller\'s map_imports folder.')
    with path.open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('The TMX import file exceeds 32 KiB.')
    try:
        content = raw.decode('utf-8-sig')
    except UnicodeError:
        raise ValueError('The TMX import file must be UTF-8 text.') from None
    seen = set()
    ids = deque()
    count = 0
    for line_no, line in enumerate(content.splitlines(), 1):
        for token in re.findall(r'[^,\s]+', line.split('#', 1)[0]):
            if not re.fullmatch(r'[0-9]{1,18}', token) or int(token) == 0:
                raise ValueError(f'Line {line_no}: expected positive TMX map IDs.')
            count += 1
            if count > MAX_IDS:
                raise ValueError(f'Use at most {MAX_IDS} map IDs per file.')
            map_id = int(token)
            if map_id not in seen:
                seen.add(map_id)
                ids.append(map_id)
    if not ids:
        raise ValueError('The TMX import file contains no map IDs.')
    return ids, count - len(ids)


def _allowed(aseco, admin):
    return matchsettings._allowed(aseco, admin) and not aseco.server.isrelay


def _preset(aseco):
    return matchsettings.filename(getattr(aseco.settings, 'default_tracklist', '') or 'MatchSettings.txt')


def _prepare_import(aseco, filename, preset):
    settings_path = matchsettings._folder(aseco) / preset
    try:
        matchsettings._check_file(aseco, preset)
    except ParseError:
        raise ValueError('The selected MatchSettings file is not valid XML.') from None
    ids, duplicates = read_ids(aseco._base_dir, filename)
    return ids, duplicates, settings_path


async def _reply(aseco, login, message):
    from .command_router import _reply as reply
    await reply(aseco, login, '{#server}> ' + message)


async def command(aseco, admin, args):
    if not _allowed(aseco, admin):
        await _reply(aseco, admin.login, 'TMX imports require an unlocked MasterAdmin on the main server.')
        return
    batch = getattr(aseco, '_tmx_map_import', None)
    if len(args) == 1 and args[0].casefold() == 'cancel':
        if batch is not None:
            batch.stop = 'Cancelled.'
        await _reply(aseco, admin.login, 'Stopping the TMX import.' if batch else 'No TMX import is running.')
        return
    if batch is not None:
        await _reply(aseco, admin.login, 'A TMX import is already running. Use //addfile cancel to stop it.')
        return
    if not 1 <= len(args) <= 2:
        await _reply(aseco, admin.login, 'Usage: //addfile maps.txt [tmnf|tmu|tmo|tms|tmn] (place the file in the controller\'s map_imports folder).')
        return
    if 'jukebox' not in aseco.active_apps or not aseco.jobs.running:
        await _reply(aseco, admin.login, 'The TMX download service is not available.')
        return
    from apps.jukebox import backend

    try:
        section = args[1].upper() if len(args) == 2 else await backend._default_tmx_section(aseco)
        if section == 'TMUF':
            section = 'TMU'
        if section not in backend.TMX_SECTION_CHOICES:
            raise ValueError('Use a TMX section: tmnf, tmu, tmo, tms, or tmn.')
        preset = _preset(aseco)
        ids, duplicates, settings_path = await file_io(_prepare_import, aseco, args[0], preset)
        if _preset(aseco) != preset:
            raise ValueError('Selected MatchSettings changed; run the import again.')
    except (OSError, ValueError) as error:
        message = str(error) if isinstance(error, ValueError) else 'Could not read the TMX import file.'
        await _reply(aseco, admin.login, message)
        return
    if not _allowed(aseco, admin):
        return
    if getattr(aseco, '_tmx_map_import', None) is not None:
        await _reply(aseco, admin.login, 'A TMX import is already running.')
        return
    aseco._tmx_map_import = ImportBatch(admin, preset, settings_path, section, ids, skipped=duplicates)
    await _reply(aseco, admin.login, f'TMX import started: {len(ids)} unique IDs from {section}. Use //addfile cancel to stop.')


def _can_continue(aseco, batch):
    if not batch.stop:
        if not _allowed(aseco, batch.admin):
            batch.stop = 'Requester disconnected, locked admin access, or lost permission.'
        elif 'jukebox' not in aseco.active_apps or not aseco.jobs.running or aseco._shutdown_requested:
            batch.stop = 'TMX download service stopped.'
        else:
            try:
                same_preset = _preset(aseco) == batch.preset
            except ValueError:
                same_preset = False
            if not same_preset:
                batch.stop = 'Selected MatchSettings changed.'
    return not batch.stop


async def tick(aseco, _event):
    batch = getattr(aseco, '_tmx_map_import', None)
    if batch is None:
        return
    running = _can_continue(aseco, batch)
    if batch.inflight:
        return
    if not running or not batch.remaining:
        aseco._tmx_map_import = None
        summary = (f'TMX import: {batch.added} added, {batch.skipped} skipped, '
                   f'{batch.rejected} rejected, {len(batch.remaining)} unprocessed.')
        if batch.stop:
            summary += ' ' + batch.stop
        logger.info('%s', summary)
        if aseco.server.players.get_player(batch.admin.login) is batch.admin:
            await _reply(aseco, batch.admin.login, summary + ' See the controller log for rejected IDs.')
        return
    now = time.monotonic()
    if now < batch.retry_at:
        return

    from apps.jukebox.tmx_jobs import get_tmx_jobs

    map_id = batch.remaining[0]

    async def guard():
        return _can_continue(aseco, batch)

    async def discarded():
        batch.inflight = False
        batch.stop = batch.stop or 'Pending map request was discarded.'

    async def complete(ok, info):
        batch.inflight = False
        if batch.stop and not ok:
            return
        batch.remaining.popleft()
        if ok:
            batch.added += 1
        elif info == 'This map is already on the server.':
            batch.skipped += 1
        else:
            batch.rejected += 1
            logger.warning('TMX import rejected ID %d: %s', map_id, info)

    try:
        outcome = await get_tmx_jobs(aseco).request(
            login=batch.admin.login, nickname=str(batch.admin.nickname), ref=str(map_id), section=batch.section,
            complete=complete, guard=guard, discarded=discarded, require_feature_flags=False,
            acknowledge=False, persist=True, queue_for_play=False, matchsettings_path=batch.settings_path,
        )
    except (OSError, RuntimeError, ValueError) as error:
        logger.warning('TMX import could not submit ID %d: %s', map_id, error)
        batch.stop = 'Could not submit the next download.'
        return
    if outcome == Admission.ACCEPTED:
        batch.inflight = True
        batch.waiting_since = None
        batch.retry_at = now + 0.5
    elif outcome == Admission.DUPLICATE:
        batch.remaining.popleft()
        batch.skipped += 1
        batch.waiting_since = None
        batch.retry_at = now + 0.5
    elif outcome in (Admission.FULL, Admission.COOLDOWN):
        if batch.waiting_since is None:
            batch.waiting_since = now
        if now - batch.waiting_since >= QUEUE_WAIT:
            batch.stop = 'TMX download queue stayed busy or unavailable.'
        batch.retry_at = now + 2
    else:
        batch.stop = 'TMX download service stopped.'
