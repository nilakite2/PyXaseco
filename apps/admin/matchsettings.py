"""MA-only MatchSettings picker, based on doe-eye/L3cKy's XAseco plugin."""

import asyncio
from pathlib import Path
import xml.etree.ElementTree as ET

from pyxaseco.core.file_io import file_io
from pyxaseco.helpers import _send_multipage


ACTION_BASE = 8550000
MAX_FILES = 1000


def filename(value):
    name = str(value or '').strip()
    if (not name or name in ('.', '..') or name.endswith(('.', ' '))
            or any(c in name for c in '/\\:<>"|?*') or any(ord(c) < 32 for c in name)):
        raise ValueError('Use a filename within the MatchSettings folder.')
    return name if name.lower().endswith('.txt') else name + '.txt'


def _folder(aseco):
    trackdir = str(getattr(aseco.server, 'trackdir', '') or '')
    if not trackdir or not Path(trackdir).is_absolute():
        raise ValueError('The picker needs access to the dedicated server\'s local track directory.')
    folder = Path(trackdir).resolve() / 'MatchSettings'
    if folder.is_symlink() or not folder.is_dir():
        raise ValueError('A regular local MatchSettings folder could not be found.')
    return folder


def _files(aseco):
    folder = _folder(aseco)
    names = []
    for path in folder.iterdir():
        if (path.suffix.lower() != '.txt' or path.name.lower() == 'autosave.txt'
                or path.is_symlink() or not path.is_file()):
            continue
        try:
            filename(path.name)
        except ValueError:
            continue
        names.append(path.name)
        if len(names) > MAX_FILES:
            raise ValueError(f'Too many MatchSettings files for the picker (maximum {MAX_FILES}).')
    return sorted(names, key=str.casefold)


def _check_file(aseco, name):
    folder = _folder(aseco)
    path = folder / name
    if path.is_symlink() or path.resolve().parent != folder or not path.is_file():
        raise ValueError('The selected MatchSettings file is no longer available.')
    with path.open('rb') as stream:
        content = stream.read(4 * 1024 * 1024 + 1)
    if len(content) > 4 * 1024 * 1024:
        raise ValueError('MatchSettings exceeds the 4 MiB size limit.')
    text = content.decode('utf-8-sig')
    if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():
        raise ValueError('MatchSettings contains unsupported XML declarations.')
    if ET.fromstring(text).tag != 'playlist':
        raise ValueError('MatchSettings must contain a playlist document.')


def _allowed(aseco, player):
    return (aseco.server.players.get_player(player.login) is player
            and aseco.is_master_admin(player)
            and (not getattr(aseco.settings, 'lock_password', '') or getattr(player, 'unlocked', False)))


def _prepare(aseco, player):
    window = getattr(player, '_ms_window', None)
    return window is not None and window is getattr(player, 'msgs', None) and _allowed(aseco, player)


async def _reply(aseco, player, message):
    from .command_router import _reply as reply
    await reply(aseco, player.login, '{#server}> ' + message)


def _remember_default(aseco):
    if not hasattr(aseco, '_ms_configured_default'):
        aseco._ms_configured_default = getattr(aseco.settings, 'default_tracklist', '') or 'MatchSettings.txt'


async def load(aseco, value='', *, player=None):
    """Share confirmed RPC loading; direct admin commands also support remote servers."""
    name = filename(value or getattr(aseco.settings, 'default_tracklist', '') or 'MatchSettings.txt')
    if not hasattr(aseco, '_ms_load_lock'):
        aseco._ms_load_lock = asyncio.Lock()
    async with aseco._ms_load_lock:
        if player is not None:
            await file_io(_check_file, aseco, name)
            if not _prepare(aseco, player):
                raise ValueError('MatchSettings access expired. Unlock admin access and reopen /ms.')
        result = await aseco.client.query('LoadMatchSettings', 'MatchSettings/' + name)
        if result is not True and not (type(result) is int and result >= 0):
            raise ValueError('The dedicated server did not confirm loading MatchSettings.')
        _remember_default(aseco)
        aseco.settings.default_tracklist = name
        aseco._ms_last_loaded = name
        await aseco.release_event('onTracklistChanged', ['read', None])
    return name


async def picker(aseco, player):
    if not _allowed(aseco, player):
        await _reply(aseco, player, '{#error}MasterAdmin access is required; unlock admin access if configured.')
        return
    names = await file_io(_files, aseco)
    if not _allowed(aseco, player):
        return
    if not names:
        await _reply(aseco, player, '{#message}No MatchSettings .txt files found (autosave.txt is hidden).')
        return
    _remember_default(aseco)
    player._ms_actions = {}
    rows = []
    for index, name in enumerate(names):
        action = ACTION_BASE + index
        player._ms_actions[action] = name
        status = []
        if name.casefold() == str(aseco._ms_configured_default).casefold():
            status.append('Configured default')
        if name.casefold() == str(getattr(aseco, '_ms_last_loaded', '')).casefold():
            status.append('Last loaded')
        rows.append([str(index + 1), ['{#black}' + name, action], ', '.join(status)])
    pages = [[['#', 'File (click to load)', 'Status']] + rows[i:i + 14] for i in range(0, len(rows), 14)]
    player.msgs = [[1, 'MatchSettings - click to load playlist/settings', [1.6, .1, .9, .6],
                    ['Icons128x128_1', 'Browse'], _prepare]] + pages
    player._ms_window = player.msgs
    await _send_multipage(aseco, player)


async def command(aseco, command):
    player = command['author']
    if not _allowed(aseco, player):
        await _reply(aseco, player, '{#error}MasterAdmin access is required; unlock admin access if configured.')
        return
    if str(command.get('params') or '').strip().lower() not in ('', 'list'):
        await _reply(aseco, player, '{#message}/ms: select a MatchSettings file. Loading also applies its game settings.')
        return
    try:
        await picker(aseco, player)
    except (OSError, ValueError) as exc:
        await _reply(aseco, player, '{#error}' + str(exc))


async def answer(aseco, answer):
    if len(answer) < 3:
        return
    try:
        action = int(answer[2])
    except (TypeError, ValueError):
        return
    if action != 0 and not ACTION_BASE <= action < ACTION_BASE + MAX_FILES:
        return
    player = aseco.server.players.get_player(answer[1])
    if player is None:
        return
    if action == 0:
        player._ms_window = None
        player._ms_actions = {}
        return
    if not _prepare(aseco, player):
        return
    name = getattr(player, '_ms_actions', {}).get(action)
    if name is None:
        return
    try:
        await load(aseco, name, player=player)
    except Exception as exc:
        await _reply(aseco, player, '{#error}Could not load MatchSettings: ' + str(exc))
        return
    aseco.console('MatchSettings: {1} loaded by {2}', name, player.login)
    from .command_router import _broadcast
    await _broadcast(aseco, '{#server}> {#admin}MatchSettings: {#highlite}' + name +
                     '{#admin} loaded by {#highlite}' + player.login)
    if _prepare(aseco, player):
        await command(aseco, {'author': player})
