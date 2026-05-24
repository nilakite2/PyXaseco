from __future__ import annotations

import asyncio
import random
from typing import TYPE_CHECKING, Any

from pyxaseco.core.base import Component

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


COMMAND_SPECS = [
    ('next', 'Forces server to load next track'),
    ('nextmap', 'Forces server to load next track'),
    ('skip', 'Forces server to skip track'),
    ('skipmap', 'Forces server to load next track'),
    ('previous', 'Forces server to load previous track'),
    ('prev', 'Forces server to load previous track'),
    ('nextenv', 'Loads next track in same environment'),
    ('restart', 'Restarts currently running track'),
    ('restartmap', 'Restarts currently running track'),
    ('res', 'Restarts currently running track'),
    ('replay', 'Replays current track (via jukebox)'),
    ('replaymap', 'Replays current track (via jukebox)'),
    ('endround', 'Forces end of current round'),
    ('er', 'Forces end of current round'),
    ('pass', 'Passes a chat-based or TMX /add vote'),
    ('cancel', 'Cancels any running vote'),
    ('can', 'Cancels any running vote'),
    ('dropjukebox', 'Drops a track from the jukebox'),
    ('djb', 'Drops a track from the jukebox'),
    ('clearjukebox', 'Clears the entire jukebox'),
    ('cjb', 'Clears the entire jukebox'),
    ('clearhist', 'Clears (part of) track history'),
    ('add', 'Adds track from TMX: /admin add <id> [tmnf|tmu|tmo|tms|tmn]'),
    ('addthis', 'Adds current /add-ed track permanently'),
    ('addlocal', 'Adds a local track (<filename>)'),
    ('remove', 'Removes a track from rotation'),
    ('erase', 'Removes a track from rotation and deletes file'),
    ('removethis', 'Removes this track from rotation'),
    ('rt', 'Removes this track from rotation'),
    ('erasethis', 'Removes this track from rotation and deletes file'),
    ('shuffle', 'Randomizes current track list'),
    ('shufflemaps', 'Randomizes current track list'),
    ('writetracklist', 'Saves current track list'),
    ('readtracklist', 'Loads current track list'),
    ('listdupes', 'Displays list of duplicate tracks'),
    ('delrec', 'Deletes specific record on current track'),
    ('prunerecs', 'Deletes records for specified track'),
]

HANDLED_SUBCOMMANDS = {name for name, _help in COMMAND_SPECS}


def can_handle(sub: str) -> bool:
    return sub in HANDLED_SUBCOMMANDS


async def handle_subcommand(
    aseco: 'Aseco',
    command: dict[str, Any],
    sub: str,
    args: list[str],
    arg: str,
    login: str,
    admin,
    logtitle: str,
    chattitle: str,
) -> bool:
    from . import chat as admin_chat

    if sub in ('nextmap', 'next', 'skipmap', 'skip'):
        skipped_jb = None
        try:
            from apps.rasp.jukebox import force_jukebox_next, jukebox

            if jukebox:
                _uid, skipped_jb = next(iter(jukebox.items()))
                jb_selected = await force_jukebox_next(aseco)
                if not jb_selected:
                    await admin_chat._reply(
                        aseco,
                        login,
                        '{#server}> {#error}Could not queue the first jukebox track as next challenge.'
                    )
                    return True
        except Exception as e:
            await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}Jukebox skip failed: {e}')
            return True

        if skipped_jb is not None:
            try:
                await aseco.release_event('onJukeboxChanged', ['skip', skipped_jb])
            except Exception:
                pass

        await aseco.client.query_ignore_result('NextChallenge')
        aseco.console('{1} [{2}] forced next challenge', logtitle, login)
        await admin_chat._broadcast(
            aseco,
            admin_chat._fmt_admin(aseco, admin, chattitle, 'skips to next track!')
        )
        return True

    if sub in ('previous', 'prev'):
        try:
            from apps.rasp.jukebox import jb_buffer

            if not isinstance(jb_buffer, list) or len(jb_buffer) < 2:
                await admin_chat._reply(
                    aseco,
                    login,
                    '{#server}> {#error}No previous track in history.'
                )
                return True

            current_uid = str(getattr(aseco.server.challenge, 'uid', '') or '').strip()
            prev_uid = ''
            for hist_uid in reversed(jb_buffer):
                hist_uid = str(hist_uid or '').strip()
                if not hist_uid:
                    continue
                if hist_uid != current_uid:
                    prev_uid = hist_uid
                    break

            if not prev_uid:
                await admin_chat._reply(
                    aseco,
                    login,
                    '{#server}> {#error}No previous track in history.'
                )
                return True

            track_list = await aseco.client.query('GetChallengeList', 5000, 0) or []
            prev_track = None
            for track in track_list:
                tuid = str(track.get('UId', '') or track.get('Uid', '') or '').strip()
                if tuid == prev_uid:
                    prev_track = track
                    break

            if not prev_track:
                await admin_chat._reply(
                    aseco,
                    login,
                    '{#server}> {#error}Previous track from history is no longer in the live track list.'
                )
                return True

            prev_filename = str(prev_track.get('FileName', '') or '').strip()
            prev_name = admin_chat.strip_colors(prev_track.get('Name', prev_uid))
            if not prev_filename:
                await admin_chat._reply(
                    aseco,
                    login,
                    '{#server}> {#error}Could not resolve previous track filename.'
                )
                return True

            await aseco.client.query_ignore_result('ChooseNextChallenge', prev_filename)
            await aseco.client.query_ignore_result('NextChallenge')
            aseco.console('{1} [{2}] loaded previous track [{3}]', logtitle, login, prev_name)
            await admin_chat._broadcast(
                aseco,
                admin_chat._fmt_admin(aseco, admin, chattitle, 'loads previous track', prev_name)
            )
        except Exception as e:
            await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}{e}')
        return True

    if sub in ('restartmap', 'restart', 'res'):
        try:
            await aseco.client.query_ignore_result('ChallengeRestart')
            aseco.console('{1} [{2}] restarted challenge', logtitle, login)
            await admin_chat._broadcast(
                aseco,
                admin_chat._fmt_admin(aseco, admin, chattitle, 'restarts this track!')
            )
        except Exception as e:
            await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}{e}')
        return True

    if sub in ('replaymap', 'replay'):
        try:
            await aseco.client.query_ignore_result('ChooseNextChallenge', aseco.server.challenge.filename)
            aseco.console('{1} [{2}] replay queued for current challenge', logtitle, login)
            await admin_chat._broadcast(
                aseco,
                admin_chat._fmt_admin(aseco, admin, chattitle, 'replays this track after finish!')
            )
        except Exception as e:
            await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}{e}')
        return True

    if sub in ('dropjukebox', 'djb'):
        try:
            from apps.rasp.jukebox import jukebox
            if not jukebox:
                await admin_chat._reply(aseco, login, '{#server}> {#error}Jukebox is empty!')
                return True
            if args and args[0].isdigit():
                idx = int(args[0]) - 1
                keys = list(jukebox.keys())
                if 0 <= idx < len(keys):
                    drop = jukebox.pop(keys[idx])
                    name = admin_chat.strip_colors(drop.get('Name', '?'))
                    await admin_chat._broadcast(
                        aseco,
                        admin_chat._fmt_admin(aseco, admin, chattitle, f'drops {name} from jukebox!')
                    )
                    await aseco.release_event('onJukeboxChanged', ['drop', drop])
                else:
                    await admin_chat._reply(aseco, login, '{#server}> {#error}Track not found in jukebox!')
            else:
                drop_uid, drop = next(iter(jukebox.items()))
                del jukebox[drop_uid]
                await admin_chat._broadcast(
                    aseco,
                    admin_chat._fmt_admin(
                        aseco, admin, chattitle,
                        f'drops {admin_chat.strip_colors(drop.get("Name","?"))} from jukebox!'
                    )
                )
                await aseco.release_event('onJukeboxChanged', ['drop', drop])
        except Exception as e:
            await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}{e}')
        return True

    if sub in ('clearjukebox', 'cjb'):
        try:
            from apps.rasp.jukebox import jukebox
            jukebox.clear()
            await admin_chat._broadcast(
                aseco,
                admin_chat._fmt_admin(aseco, admin, chattitle, 'clears the entire jukebox!')
            )
        except Exception as e:
            await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}{e}')
        return True

    if sub == 'clearhist':
        try:
            from apps.rasp.jukebox import jb_buffer

            buf = jb_buffer
            if not isinstance(buf, list):
                await admin_chat._reply(aseco, login, '{#server}> {#error}Track history buffer unavailable.')
                return True

            raw_arg = arg.strip().lower()
            buf_len = len(buf)
            if raw_arg == '':
                await admin_chat._reply(
                    aseco,
                    login,
                    f'{{#server}}> {{#message}}The track history contains {{#highlite}}{buf_len}{{#message}} track{"s" if buf_len != 1 else ""}.'
                )
                return True

            if raw_arg == 'all':
                clear = buf_len
                aseco.console('{1} [{2}] clears entire track history!', logtitle, login)
                await admin_chat._broadcast(
                    aseco,
                    admin_chat._fmt_admin(aseco, admin, chattitle, 'clears entire track history!')
                )
            elif raw_arg.lstrip('-').isdigit() and raw_arg != '0':
                clear = int(raw_arg)
                desc = f'newest {abs(clear)}' if clear > 0 else f'oldest {abs(clear)}'
                aseco.console('{1} [{2}] clears {3} track{4} from history!', logtitle, login, desc, '' if abs(clear) == 1 else 's')
                await admin_chat._broadcast(
                    aseco,
                    admin_chat._fmt_admin(
                        aseco, admin, chattitle,
                        f'clears {desc} track{"s" if abs(clear) != 1 else ""} from history!'
                    )
                )
            else:
                await admin_chat._reply(
                    aseco,
                    login,
                    f'{{#server}}> {{#message}}The track history contains {{#highlite}}{buf_len}{{#message}} track{"s" if buf_len != 1 else ""}.'
                )
                return True

            if clear > 0:
                clear = min(clear, len(buf))
                for _ in range(clear):
                    buf.pop()
            else:
                clear = max(clear, -len(buf))
                for _ in range(abs(clear)):
                    buf.pop(0)
        except Exception as e:
            await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}{e}')
        return True

    if sub == 'pass':
        try:
            from apps.rasp.voting import chatvote, tmxadd
            from apps.rasp.jukebox import chat_y
            if chatvote or tmxadd:
                if chatvote:
                    chatvote['votes'] = 0
                elif tmxadd:
                    tmxadd['votes'] = 0
                await chat_y(aseco, command)
                aseco.console('{1} [{2}] passed vote', logtitle, login)
            else:
                await admin_chat._reply(aseco, login, '{#server}> {#error}No vote in progress!')
        except Exception as e:
            await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}{e}')
        return True

    if sub in ('cancel', 'can'):
        try:
            from apps.rasp.voting import chatvote, tmxadd
            if chatvote:
                aseco.console('{1} [{2}] cancelled vote', logtitle, login)
                msg = admin_chat.format_text('{#server}>> {#error}Vote cancelled by admin.')
                await aseco.client.query_ignore_result('ChatSendServerMessage', aseco.format_colors(msg))
                chatvote.clear()
            elif tmxadd:
                tmxadd.clear()
                msg = admin_chat.format_text('{#server}>> {#error}TMX vote cancelled by admin.')
                await aseco.client.query_ignore_result('ChatSendServerMessage', aseco.format_colors(msg))
            else:
                await admin_chat._reply(aseco, login, '{#server}> {#error}No vote in progress!')
        except Exception as e:
            await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}{e}')
        return True

    if sub in ('endround', 'er'):
        await aseco.client.query_ignore_result('ForceEndRound')
        aseco.console('{1} [{2}] forced end of round', logtitle, login)
        await admin_chat._broadcast(
            aseco,
            admin_chat._fmt_admin(aseco, admin, chattitle, 'forces end of current round!')
        )
        return True

    if sub in ('writetracklist',):
        await admin_chat._reply(aseco, login, '{#server}> MatchSettings.txt is maintained automatically.')
        return True

    if sub == 'readtracklist':
        try:
            await aseco.client.query_ignore_result('LoadMatchSettings', 'MatchSettings/MatchSettings.txt')
            await admin_chat._broadcast(
                aseco,
                admin_chat._fmt_admin(aseco, admin, chattitle, 'reloads track list!')
            )
        except Exception as e:
            await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}{e}')
        return True

    if sub in ('shuffle', 'shufflemaps'):
        try:
            track_list = await aseco.client.query('GetChallengeList', 5000, 0) or []
            random.shuffle(track_list)
            file_names = [t['FileName'] for t in track_list]
            await aseco.client.query_ignore_result('SetChallengeList', file_names)
            aseco.console('{1} [{2}] shuffled track list', logtitle, login)
            await admin_chat._broadcast(
                aseco,
                admin_chat._fmt_admin(aseco, admin, chattitle, 'shuffles track list!')
            )
        except Exception as e:
            await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}{e}')
        return True

    if sub == 'erase' and arg:
        try:
            if arg.strip().isdigit() and hasattr(admin, 'tracklist'):
                idx = int(arg.strip()) - 1
                if not (0 <= idx < len(admin.tracklist)):
                    await admin_chat._reply(aseco, login, '{#server}> {#error}Track index out of range.')
                    return True
                fname = admin.tracklist[idx].get('filename', '')
            else:
                fname = arg.strip()

            if not fname:
                await admin_chat._reply(aseco, login, '{#server}> {#error}Missing track filename.')
                return True

            uid = await admin_chat._find_track_uid_by_filename(aseco, fname)
            await admin_chat._remove_track_from_rotation(aseco, fname, uid)
            await admin_chat._erase_track_from_localdb(aseco, uid)

            try:
                gbx_path = admin_chat._resolve_track_path(aseco, fname)
                if gbx_path.exists():
                    gbx_path.unlink()
            except Exception as e:
                aseco.console('[Admin] erase file warning: {1}', str(e))

            aseco.console('{1} [{2}] erased track [{3}]', logtitle, login, fname)
            await admin_chat._broadcast(
                aseco,
                admin_chat._fmt_admin(aseco, admin, chattitle, 'erases track', fname)
            )
        except Exception as e:
            await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}{e}')
        return True

    if sub in ('removethis', 'rt'):
        fname = aseco.server.challenge.filename
        uid = aseco.server.challenge.uid
        try:
            await admin_chat._remove_track_from_rotation(aseco, fname, uid)
            aseco.console('{1} [{2}] removed current track', logtitle, login)
            await admin_chat._broadcast(
                aseco,
                admin_chat._fmt_admin(aseco, admin, chattitle, 'removes current track from rotation!')
            )
            await aseco.client.query_ignore_result('NextChallenge')
        except Exception as e:
            await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}{e}')
        return True

    if sub == 'erasethis':
        fname = aseco.server.challenge.filename
        uid = getattr(aseco.server.challenge, 'uid', '')
        try:
            await admin_chat._remove_track_from_rotation(aseco, fname, uid)
            await admin_chat._erase_track_from_localdb(aseco, uid)
            try:
                gbx_path = admin_chat._resolve_track_path(aseco, fname)
                if gbx_path.exists():
                    gbx_path.unlink()
            except Exception as e:
                aseco.console('[Admin] erasethis file warning: {1}', str(e))

            aseco.console('{1} [{2}] erased current track', logtitle, login)
            await admin_chat._broadcast(
                aseco,
                admin_chat._fmt_admin(aseco, admin, chattitle, 'erases current track!')
            )
            await aseco.client.query_ignore_result('NextChallenge')
        except Exception as e:
            await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}{e}')
        return True

    if sub == 'remove' and arg:
        try:
            if arg.strip().isdigit() and hasattr(admin, 'tracklist'):
                idx = int(arg.strip()) - 1
                if not (0 <= idx < len(admin.tracklist)):
                    await admin_chat._reply(aseco, login, '{#server}> {#error}Track index out of range.')
                    return True
                fname = admin.tracklist[idx].get('filename', '')
                uid = admin.tracklist[idx].get('uid', '')
            else:
                fname = arg.strip()
                uid = await admin_chat._find_track_uid_by_filename(aseco, fname)

            if not fname:
                await admin_chat._reply(aseco, login, '{#server}> {#error}Missing track filename.')
                return True

            if not uid:
                uid = await admin_chat._find_track_uid_by_filename(aseco, fname)

            await admin_chat._remove_track_from_rotation(aseco, fname, uid)
            aseco.console('{1} [{2}] removed track [{3}]', logtitle, login, fname)
            await admin_chat._broadcast(
                aseco,
                admin_chat._fmt_admin(aseco, admin, chattitle, 'removes track', fname)
            )
        except Exception as e:
            await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}{e}')
        return True

    if sub == 'nextenv':
        try:
            env = aseco.server.challenge.environment
            track_list = await aseco.client.query('GetChallengeList', 5000, 0) or []
            for track in track_list:
                if track.get('Environnement', '') == env and track['FileName'] != aseco.server.challenge.filename:
                    await aseco.client.query_ignore_result('SetNextChallengeList', [track])
                    await aseco.client.query_ignore_result('NextChallenge')
                    await admin_chat._reply(aseco, login, f'{{#server}}> Next env track: {{#highlite}}{track.get("Name", "?")}')
                    return True
            await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}No other {env} tracks found.')
        except Exception as e:
            await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}{e}')
        return True

    if sub == 'add':
        if not args:
            await admin_chat._reply(aseco, login, '{#server}> {#error}Usage: {#highlite}/admin add <TMX_ID>... [tmnf|tmu|...]')
            return True

        sections = {'tmnf', 'tmu', 'tmo', 'tms', 'tmn'}
        source_hint = ''
        track_ids = []
        for value in args:
            if value.lower() in sections:
                source_hint = value.lower()
            elif value.isdigit():
                track_ids.append(value)
            else:
                await admin_chat._reply(aseco, login, f'{{#server}}> {{#highlite}}{value}{{#error}} is not a valid TMX Track_ID!')

        if not track_ids:
            await admin_chat._reply(aseco, login, '{#server}> {#error}You must include a TMX Track_ID!')
            return True

        jukebox_adminadd = True
        for trkid in track_ids:
            try:
                from apps.rasp.jukebox import admin_add_tmx_track
                ok, info = await admin_add_tmx_track(
                    aseco, trkid, login, source_hint, use_add_challenge=True
                )
                if ok:
                    track_name = info
                    aseco.console('{1} [{2}] adds track "{3}" from TMX!', logtitle, login, track_name)
                    jb_phrase = '& jukeboxes ' if jukebox_adminadd else ''
                    msg = admin_chat.format_text(
                        '{#server}>> {#admin}{1}$z$s {#highlite}{2}$z$s {#admin}adds {3}track: {#highlite}{4} {#admin}from TMX',
                        chattitle, admin.nickname, jb_phrase, track_name
                    )
                    await admin_chat._broadcast(aseco, msg)
                else:
                    await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}Could not add {trkid}: {info}')
            except Exception as e:
                await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}{e}')
        return True

    if sub == 'addthis':
        try:
            from apps.rasp.jukebox import tmxplayed
        except Exception:
            tmxplayed = None

        try:
            if not tmxplayed:
                await admin_chat._reply(
                    aseco,
                    login,
                    f'{{#server}}> {{#error}}Current track {{#highlite}}$i {admin_chat.strip_colors(aseco.server.challenge.name)} {{#error}}already permanently in track list!'
                )
                return True

            try:
                from apps.rasp.jukebox import _matchsettings_path, _ensure_matchsettings_entry
            except Exception:
                _matchsettings_path = None
                _ensure_matchsettings_entry = None

            filename = aseco.server.challenge.filename
            uid = getattr(aseco.server.challenge, 'uid', '')

            if _matchsettings_path and _ensure_matchsettings_entry and uid:
                await asyncio.to_thread(
                    _ensure_matchsettings_entry,
                    _matchsettings_path(aseco),
                    filename,
                    uid
                )

            try:
                import apps.rasp.jukebox as rasp_jukebox_mod
                rasp_jukebox_mod.tmxplayed = False
            except Exception:
                pass

            await aseco.release_event('onTracklistChanged', ['rename', filename])
            aseco.console('{1} [{2}] permanently adds current track [{3}]', logtitle, login, admin_chat.strip_colors(aseco.server.challenge.name))
            await admin_chat._broadcast(
                aseco,
                admin_chat._fmt_admin(
                    aseco, admin, chattitle, 'permanently adds current track:', admin_chat.strip_colors(aseco.server.challenge.name)
                )
            )
        except Exception as e:
            await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}{e}')
        return True

    if sub == 'addlocal':
        if arg:
            try:
                rel_insert = arg.strip()
                await aseco.client.query_ignore_result('InsertChallenge', rel_insert)
                await aseco.release_event('onTracklistChanged', ['add', rel_insert])

                try:
                    from apps.rasp.jukebox import _parse_gbx_metadata, _matchsettings_path, _ensure_matchsettings_entry

                    gbx_path = (aseco._base_dir.parent / 'GameData' / 'Tracks' / rel_insert).resolve()
                    metadata = await asyncio.to_thread(_parse_gbx_metadata, gbx_path)
                    uid = metadata.get('uid', '').strip()

                    if uid:
                        await asyncio.to_thread(
                            _ensure_matchsettings_entry,
                            _matchsettings_path(aseco),
                            rel_insert,
                            uid
                        )

                        pool = await admin_chat.localdb_get_pool(aseco)
                        if pool:
                            async with pool.acquire() as conn:
                                async with conn.cursor() as cur:
                                    await cur.execute(
                                        'INSERT INTO challenges (Uid, Name, Author, Environment) '
                                        'VALUES (%s, %s, %s, %s) '
                                        'ON DUPLICATE KEY UPDATE Name=VALUES(Name), Author=VALUES(Author), Environment=VALUES(Environment)',
                                        (
                                            uid,
                                            metadata.get('name', ''),
                                            metadata.get('author', ''),
                                            metadata.get('environment', '')
                                        )
                                    )
                            try:
                                from pyxaseco.core.challenges_cache import upsert_for_track
                                await upsert_for_track(
                                    aseco,
                                    pool,
                                    uid=uid,
                                    name=metadata.get('name', ''),
                                    author=metadata.get('author', ''),
                                    environment=metadata.get('environment', ''),
                                    filename=rel_insert,
                                )
                            except Exception as cache_exc:
                                aseco.console('[Admin] addlocal challenges_extra warning: {1}', str(cache_exc))

                        try:
                            await aseco.client.query_ignore_result('LoadMatchSettings', 'MatchSettings/MatchSettings.txt')
                        except Exception as e:
                            aseco.console('[Admin] addlocal reload warning: {1}', str(e))

                except Exception as e:
                    aseco.console('[Admin] addlocal post-sync warning: {1}', str(e))

                await admin_chat._reply(aseco, login, f'{{#server}}> Added local track: {{#highlite}}{rel_insert}')
            except Exception as e:
                await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}{e}')
        return True

    if sub == 'listdupes':
        try:
            tracks = await aseco.client.query('GetChallengeList', 5000, 0) or []
            names: dict[str, bool] = {}
            dupes = []
            for track in tracks:
                name = track.get('Name', '')
                if name in names:
                    dupes.append(name)
                else:
                    names[name] = True
            if dupes:
                header = 'Duplicate tracks:'
                rows = [[f'{i + 1:02d}.', admin_chat.strip_colors(name)] for i, name in enumerate(dupes)]
                admin_chat.display_manialink(
                    aseco, login, header,
                    ['Icons64x64_1', 'TrackInfo', -0.01],
                    rows, [0.8, 0.1, 0.7], 'OK'
                )
            else:
                await admin_chat._reply(aseco, login, '{#server}> No duplicate tracks found.')
        except Exception as e:
            await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}{e}')
        return True

    if sub in ('delrec', 'prunerecs'):
        await admin_chat._delegate_if_exists(
            aseco, login,
            'apps.records_eyepiece.app:chat_admin_records',
            aseco, command,
            unavailable_msg='{#server}> {#admin}Record admin commands unavailable - include app/records_eyepiece'
        )
        return True

    return False


def _register_specs(aseco: 'Aseco') -> None:
    for order, (name, help_text) in enumerate(COMMAND_SPECS, start=200):
        aseco.register_command(
            f'admin/{name}',
            help_text,
            is_admin=True,
            owner='chat/admin',
            app='admin',
            category='admin-map',
            parent='admin',
            usage=f'/admin {name}',
            display_name=name,
            public=False,
            permission=name,
            order=order,
        )


class AdminMapDomain(Component):
    def __init__(self):
        super().__init__(
            component_id='admin.map',
            description='Map rotation, jukebox, TMX add, and record-maintenance commands.',
        )

    def register(self, aseco: 'Aseco') -> None:
        _register_specs(aseco)


MAP_DOMAIN = AdminMapDomain()


def get_component() -> AdminMapDomain:
    return MAP_DOMAIN


__all__ = [
    'COMMAND_SPECS',
    'HANDLED_SUBCOMMANDS',
    'can_handle',
    'handle_subcommand',
    'AdminMapDomain',
    'MAP_DOMAIN',
    'get_component',
]
