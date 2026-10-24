"""Bounded local XML status exchange, compatible with XAseco's status files."""

import hashlib
import os
from pathlib import Path
import re
import time
from uuid import uuid4
import xml.etree.ElementTree as ET


MAX_BYTES = 256 * 1024
MAX_SERVERS = 100
LOGIN = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,74}')
SUFFIX = '_serverinfo.xml'


def valid_login(value):
    if not isinstance(value, str) or not LOGIN.fullmatch(value):
        raise ValueError('Server logins must contain only letters, digits, dots, underscores or hyphens.')
    return value


def directory(root, value):
    value = str(value).strip()
    if not value or '://' in value or value.startswith(('\\\\', '//')):
        raise ValueError('Choose a local status folder, not an FTP/HTTP/UNC address.')
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = Path(root) / path
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise ValueError('Status directory must be a regular folder.')
    return path.resolve()


def owner(root):
    return hashlib.sha256(os.path.normcase(str(Path(root).resolve())).encode('utf-8')).hexdigest()


def _read(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('Status files must be regular files, not symbolic links.')
    with path.open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    decoded = raw.decode('utf-8-sig')
    if len(raw) > MAX_BYTES or '<!DOCTYPE' in decoded.upper() or '<!ENTITY' in decoded.upper():
        raise ValueError('Status XML is oversized or contains a forbidden declaration.')
    root = ET.fromstring(raw)
    if root.tag != 'server_neighborhood':
        raise ValueError('Unexpected status XML root.')
    if root.findtext('server/game', 'TMF') != 'TMF':
        raise ValueError('Status belongs to a different game.')
    return root


def _count(value):
    number = int(value)
    if not 0 <= number <= 100000:
        raise ValueError('Invalid player/spectator capacity.')
    return number


def read(path, login):
    root = _read(path)
    if root.findtext('server/login') != login:
        raise ValueError('Status filename and server login disagree.')
    def text(key, default='', limit=160):
        return str(root.findtext(key, default) or default).replace('\r', ' ').replace('\n', ' ')[:limit]
    stamp = float(root.findtext('server/last_modified', '0'))
    if not 0 <= stamp < 1e12:
        raise ValueError('Invalid status timestamp.')
    return {'login': login, 'name': text('server/name', login), 'updated': stamp,
            'online': text('server/online', 'true').lower() == 'true',
            'mode': int(text('server/gamemode', '-1')), 'pack': text('server/packmask', '', 30),
            'players': _count(text('server/players/current', '0')),
            'maxplayers': _count(text('server/players/maximum', '0')),
            'spectators': _count(text('server/spectators/current', '0')),
            'maxspectators': _count(text('server/spectators/maximum', '0')),
            'map': text('current/map/name'), 'author': text('current/map/author'),
            'environment': text('current/map/environment', '', 30)}


def write(folder, data, publisher):
    login = valid_login(data['login'])
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    if folder.is_symlink():
        raise ValueError('Status directory may not be a symbolic link.')
    target = folder / (login + SUFFIX)
    replacing = target.exists() or target.is_symlink()
    if replacing:
        previous = _read(target)
        if previous.get('pyxaseco_owner') != publisher or previous.findtext('server/login') != login:
            raise ValueError('Another installation owns this server status filename; nothing was overwritten.')
    root = ET.Element('server_neighborhood', pyxaseco_owner=publisher)
    server = ET.SubElement(root, 'server')
    for key, value in (('login', login), ('name', data['name']), ('last_modified', data['updated']),
                       ('online', str(data['online']).lower()), ('game', 'TMF'),
                       ('gamemode', data['mode']), ('packmask', data['pack'])):
        ET.SubElement(server, key).text = str(value)
    for name, current, maximum in (('players', data['players'], data['maxplayers']),
                                    ('spectators', data['spectators'], data['maxspectators'])):
        node = ET.SubElement(server, name)
        ET.SubElement(node, 'current').text = str(current)
        ET.SubElement(node, 'maximum').text = str(maximum)
    current = ET.SubElement(root, 'current')
    track = ET.SubElement(current, 'map')
    for key in ('name', 'author', 'environment'):
        ET.SubElement(track, key).text = str(data['map' if key == 'name' else key])
    # No player roster, network endpoints, passwords or database settings are exported.
    ET.SubElement(current, 'players')
    raw = ET.tostring(root, encoding='utf-8', xml_declaration=True)
    if len(raw) > MAX_BYTES:
        raise ValueError('Local status exceeds the XML size limit.')
    temporary = folder / ('.' + login + '.' + uuid4().hex + '.tmp')
    try:
        with temporary.open('xb') as stream:
            os.chmod(temporary, 0o600)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if replacing:
            os.replace(temporary, target)
        else:
            # Exclusive first publication: two controllers cannot claim the same login.
            os.link(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def scan(folder, logins=()):
    if folder.is_symlink():
        raise ValueError('Unsafe status directory.')
    names = list(logins)
    if not names and folder.exists():
        names = []
        for path in folder.glob('*' + SUFFIX):
            login = path.name[:-len(SUFFIX)]
            if LOGIN.fullmatch(login):
                names.append(login)
            if len(names) > MAX_SERVERS:
                raise ValueError('More than 100 server statuses; configure server_logins to select a group.')
        names.sort(key=str.casefold)
    rows, errors = [], []
    for login in names:
        try:
            rows.append(read(folder / (valid_login(login) + SUFFIX), login))
        except (OSError, ValueError, ET.ParseError) as error:
            errors.append(login + ': ' + str(error))
            rows.append({'login': login, 'name': login, 'updated': 0, 'online': False,
                         'players': 0, 'maxplayers': 0, 'spectators': 0, 'maxspectators': 0,
                         'mode': -1, 'pack': '', 'map': '', 'author': '', 'environment': ''})
    return rows, errors


def status(row, stale_seconds, now=None):
    now = time.time() if now is None else now
    if not row['updated']:
        return 'unavailable'
    if not row['online']:
        return 'offline'
    if row['updated'] > now + 300 or now - row['updated'] > stale_seconds:
        return 'stale'
    return 'full' if row['maxplayers'] and row['players'] >= row['maxplayers'] else 'online'
