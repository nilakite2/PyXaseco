"""Confirmed current-map replacement without deleting files or record history."""

from dataclasses import dataclass
import logging
import time
import xml.etree.ElementTree as ET

from pyxaseco.core.background_jobs import Admission
from pyxaseco.core.file_io import file_io
from pyxaseco.core.playlist import playlist
from pyxaseco.helpers import clean_tm_text
from pyxaseco.management.config_store import revision, update_file

from . import matchsettings


logger = logging.getLogger(__name__)
MAX_SETTINGS = 4 * 1024 * 1024
PLAN_SECONDS = 90


@dataclass(frozen=True)
class Plan:
    uid: str
    filename: str
    settings_name: str
    revision: str
    generation: int
    track_id: int
    section: str
    expires: float


def _name(aseco):
    return matchsettings.filename(getattr(aseco.settings, 'default_tracklist', '') or 'MatchSettings.txt')


def _key(filename):
    return str(filename or '').replace('\\', '/').strip().casefold()


def _track(row):
    return str(row.get('UId') or row.get('Uid') or ''), str(row.get('FileName') or '')


def _allowed(aseco, player):
    return matchsettings._allowed(aseco, player) and not getattr(aseco.server, 'isrelay', False)


def _matches(aseco, player, plan):
    challenge = aseco.server.challenge
    return (_allowed(aseco, player) and challenge.uid == plan.uid
            and _key(challenge.filename) == _key(plan.filename) and _name(aseco) == plan.settings_name
            and getattr(aseco, '_map_generation', 0) == plan.generation)


def _download_filename(aseco, path):
    root = matchsettings._folder(aseco).parent
    try:
        relative = path.resolve(strict=True).relative_to(root)
    except (OSError, ValueError) as error:
        raise ValueError('The download is not in the dedicated server track directory.') from error
    if len(relative.parts) < 2 or relative.parts[0].casefold() != 'challenges':
        raise ValueError('The download is not in the dedicated server Challenges folder.')
    return '\\'.join(relative.parts)


def _read(aseco, name):
    matchsettings._check_file(aseco, name)
    path = matchsettings._folder(aseco) / name
    with path.open('rb') as stream:
        content = stream.read(MAX_SETTINGS + 1)
    if len(content) > MAX_SETTINGS:
        raise ValueError('MatchSettings exceeds the 4 MiB editing limit.')
    return path, content


def _settings_tree(raw, uid, filename):
    text = raw.decode('utf-8-sig')
    upper = text.upper()
    if '<!DOCTYPE' in upper or '<!ENTITY' in upper:
        raise ValueError('Unsupported MatchSettings XML declarations.')
    root = ET.fromstring(text, parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)))
    if root.tag != 'playlist':
        raise ValueError('MatchSettings is not a playlist.')
    found = [item for item in root.findall('challenge') if (item.findtext('ident') or '').strip() == uid
             or _key(item.findtext('file') or '') == _key(filename)]
    if (len(found) != 1 or (found[0].findtext('ident') or '').strip() != uid
            or _key(found[0].findtext('file') or '') != _key(filename)):
        raise ValueError('The current map does not have one exact UID/file entry in the selected MatchSettings.')
    return root, found[0]


def _new_settings(raw, plan, uid, filename):
    root, old = _settings_tree(raw, plan.uid, plan.filename)
    if any(item is not old and ((item.findtext('ident') or '').strip() == uid
                                or _key(item.findtext('file') or '') == _key(filename))
           for item in root.findall('challenge')):
        raise ValueError('The replacement is already in the saved rotation.')
    old.find('file').text = filename
    old.find('ident').text = uid
    return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding='unicode') + '\n'


def _parse_plan(aseco, uid, filename, name):
    _path, raw = _read(aseco, name)
    _settings_tree(raw, uid, filename)
    return revision(raw)


async def _live(aseco):
    rows = await playlist(aseco).snapshot(refresh=True)
    return tuple((uid, _key(filename)) for uid, filename in map(_track, rows))


async def _current(aseco):
    row = await aseco.client.query('GetCurrentChallengeInfo')
    if not isinstance(row, dict):
        raise ValueError('The dedicated server did not confirm its current map.')
    uid, filename = _track(row)
    return uid, _key(filename)


async def _rpc(aseco, method, filename):
    if await aseco.client.query(method, filename) is not True:
        raise ValueError(f'The dedicated server rejected {method}.')


async def _undo_insert(aseco, filename, new, old):
    try:
        rows = await _live(aseco)
        if rows.count(old) != 1:
            return False
        if new in rows:
            if rows.count(new) != 1 or await _current(aseco) == new:
                return False
            await _rpc(aseco, 'RemoveChallenge', filename)
        rows = await _live(aseco)
        return old in rows and new not in rows
    except Exception:
        logger.warning('[ReplaceMap] Could not verify removal of the staged map', exc_info=True)
        return False


async def commit(aseco, player, plan, promoted):
    from apps.jukebox.backend import _discard_downloaded_track

    path, _relative, _host, _track_id, metadata = promoted
    uid = str(metadata.get('uid') or '').strip()
    old = (plan.uid, _key(plan.filename))
    stage = 'checking'
    saved = None
    try:
        if not _matches(aseco, player, plan):
            raise ValueError('The current map or admin access changed; nothing replaced.')
        filename = await file_io(_download_filename, aseco, path)
        new = (uid, _key(filename))
        settings_path, raw = await file_io(_read, aseco, plan.settings_name)
        if revision(raw) != plan.revision:
            raise ValueError('MatchSettings changed since preview. Start again.')
        if not uid or old[1] == new[1]:
            raise ValueError('The download has no new map file to install.')
        draft = _new_settings(raw, plan, uid, filename)
        before = await _live(aseco)
        if await _current(aseco) != old or before.count(old) != 1:
            raise ValueError('The live current map changed or its rotation slot is ambiguous.')
        if any(row != old and (row[0] == uid or row[1] == new[1]) for row in before):
            raise ValueError('The replacement is already in the live rotation.')
        await _rpc(aseco, 'CheckChallengeForCurrentServerParams', filename)
        if not _matches(aseco, player, plan):
            raise ValueError('The current map or admin access changed; nothing replaced.')
        slot = before.index(old)
        staged = before[:slot + 1] + (new,) + before[slot + 1:]
        final = before[:slot] + (new,) + before[slot + 1:]
        stage = 'inserting'
        await _rpc(aseco, 'InsertChallenge', filename)
        if await _live(aseco) != staged or not _matches(aseco, player, plan):
            raise ValueError('The replacement could not be verified directly after the current map.')
        saved = await file_io(update_file, settings_path, lambda _old: draft, expected=plan.revision)
        stage = 'removing'
        if not _matches(aseco, player, plan) or await _current(aseco) != old or await _live(aseco) != staged:
            raise ValueError('The live rotation changed before the final swap.')
        checked_path, checked_raw = await file_io(_read, aseco, plan.settings_name)
        if checked_path != settings_path or revision(checked_raw) != saved.revision:
            raise ValueError('MatchSettings changed before the final swap.')
        if not _matches(aseco, player, plan):
            raise ValueError('The current map or admin access changed before the final swap.')
        try:
            await _rpc(aseco, 'RemoveChallenge', plan.filename)
        except Exception:
            logger.warning('[ReplaceMap] Old-map removal was not acknowledged; verifying rotation')
        after = await _live(aseco)
        if after != final:
            raise ValueError('The server did not confirm the expected final rotation.')
    except Exception as error:
        logger.warning('[ReplaceMap] Replacement failed during %s: %s', stage, error)
        if saved is not None:
            try:
                rows = await _live(aseco)
                if old not in rows:
                    return False, 'Could not verify the rotation. Both GBX files were kept; inspect the live and saved lists.'
                await file_io(update_file, settings_path, lambda _old: raw.decode('utf-8'),
                              expected=saved.revision, backup=False)
            except Exception:
                logger.warning('[ReplaceMap] Could not restore MatchSettings; retained both files', exc_info=True)
                return False, 'Could not restore MatchSettings automatically. Both GBX files were kept; inspect the lists.'
        if stage != 'checking' and not await _undo_insert(aseco, filename, new, old):
            return False, 'The staged map could not be removed safely. Both GBX files were kept; inspect the rotation.'
        try:
            await file_io(_discard_downloaded_track, path, metadata)
        except OSError:
            logger.warning('[ReplaceMap] Could not clean unused download %s', path)
        detail = str(error) if isinstance(error, ValueError) else type(error).__name__
        return False, detail + ' The original GBX and records were kept.'

    await aseco.release_event('onTracklistChanged', ['replace', filename])
    name = clean_tm_text(metadata.get('name') or filename, keep_colors=False)
    note = ' Same UID; existing records were kept.' if uid == plan.uid else ' New UID; old records were not moved.'
    return True, name + ' replaced the current rotation slot. No map change was forced.' + note


async def command(aseco, player, args):
    from apps.jukebox import backend
    from apps.jukebox.tmx_jobs import get_tmx_jobs

    async def reply(message, *, error=False):
        await matchsettings._reply(aseco, player, ('{#error}' if error else '{#message}') + message)

    if not _allowed(aseco, player):
        await reply('Replacing maps requires an unlocked MasterAdmin on the main server.', error=True)
        return
    try:
        verb = args[0].casefold() if len(args) == 1 else ''
        if verb == 'cancel':
            player._replace_map_plan = None
            player._replace_map_request = None
            await reply('Pending map replacement cancelled.')
            return
        if getattr(player, '_replace_map_request', None) is not None:
            await reply('A replacement is already preparing. Wait or use //replacemap cancel.', error=True)
            return
        if verb == 'confirm':
            plan = getattr(player, '_replace_map_plan', None)
            player._replace_map_plan = None
            if plan is None or plan.expires <= time.monotonic() or not _matches(aseco, player, plan):
                raise ValueError('No valid replacement preview. Start with //replacemap <TMX ID or URL>.')

            async def allowed():
                return getattr(player, '_replace_map_request', None) is plan and _matches(aseco, player, plan)

            async def complete(ok, message):
                if getattr(player, '_replace_map_request', None) is plan:
                    player._replace_map_request = None
                    await reply(message, error=not ok)

            async def discarded():
                await complete(False, 'Replacement cancelled after the map or admin access changed.')

            async def replace(promoted):
                return await commit(aseco, player, plan, promoted)

            player._replace_map_request = plan
            try:
                result = await get_tmx_jobs(aseco).request(
                    login=player.login, nickname=player.nickname, ref=str(plan.track_id), section=plan.section,
                    complete=complete, require_feature_flags=False, current_map=True,
                    guard=allowed, discarded=discarded, apply_promoted=replace,
                )
            except BaseException:
                player._replace_map_request = None
                raise
            if result != Admission.ACCEPTED and _matches(aseco, player, plan):
                player._replace_map_plan = plan
            if result != Admission.ACCEPTED:
                player._replace_map_request = None
            return

        player._replace_map_plan = None
        if not 1 <= len(args) <= 2:
            await reply('Usage: //replacemap <TMX ID or URL> [section], then //replacemap confirm.')
            return
        if 'jukebox' not in aseco.active_apps:
            raise ValueError('Map replacement needs the Jukebox app for TMX downloads.')
        hint = args[1] if len(args) == 2 else await backend._default_tmx_section(aseco)
        host, track_id = backend.parse_tmx_reference(args[0], hint)
        challenge = aseco.server.challenge
        uid, filename = challenge.uid, challenge.filename
        if not uid or not filename:
            raise ValueError('There is no current map to replace.')
        name = _name(aseco)
        generation = getattr(aseco, '_map_generation', 0)
        stamp = await file_io(_parse_plan, aseco, uid, filename, name)
        plan = Plan(uid, filename, name, stamp, generation, track_id, backend._tmx_section_for_public_host(host),
                    time.monotonic() + PLAN_SECONDS)
        if not _matches(aseco, player, plan):
            raise ValueError('The current map changed; start again.')
        player._replace_map_plan = plan
        label = clean_tm_text(challenge.name or filename, keep_colors=False)
        await reply(f'Replace {label} in {name} with {plan.section} #{track_id}? '
                    'Old GBX and records are kept. Use //replacemap confirm within 90 seconds.')
    except (ValueError, OSError, RuntimeError, ET.ParseError) as error:
        await reply(str(error), error=True)
