"""Backed-up event-server resets; the dedicated server always stays online."""

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import secrets
from time import monotonic
import xml.etree.ElementTree as ET

import aiomysql

from pyxaseco.app_services import get_localdb_service, localdb_get_pool
from pyxaseco.core.file_io import file_io
from pyxaseco.management.config_store import ManagementError, update_file


logger = logging.getLogger(__name__)
SYSTEM_DATABASES = {'mysql', 'sys', 'information_schema', 'performance_schema'}
TTL = 120


@dataclass(frozen=True)
class Plan:
    mode: str
    database: str = ''
    tables: tuple = ()
    settings: dict = field(default_factory=dict, repr=False)
    matchsettings: Path | None = None
    revision: str = ''


def _identifier(value):
    return '`' + value.replace('`', '``') + '`'


def _playlist_document(text):
    if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():
        raise ManagementError('MatchSettings contains unsupported XML declarations')
    root = ET.fromstring(text, parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)))
    if root.tag != 'playlist':
        raise ManagementError('MatchSettings must contain a playlist document')
    return root


def _keep_current_playlist(text, uid, filename):
    root = _playlist_document(text)
    current = next((deepcopy(challenge) for challenge in root.findall('challenge')
                    if challenge.findtext('ident') == uid or
                    (challenge.findtext('file') or '').replace('\\', '/') == filename.replace('\\', '/')), None)
    if current is None:
        current = ET.Element('challenge')
    for tag, value in (('file', filename), ('ident', uid)):
        node = current.find(tag)
        if node is None:
            node = ET.SubElement(current, tag)
        node.text = value
    for challenge in list(root.findall('challenge')):
        root.remove(challenge)
    root.append(current)
    for index in root.findall('startindex'):
        index.text = '0'
    return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding='unicode') + '\n'


def _playlist_target(aseco):
    filename = str(getattr(aseco.settings, 'default_tracklist', '') or 'MatchSettings.txt')
    if Path(filename).name != filename or any(ch in filename for ch in '/\\:\0'):
        raise ManagementError('default_tracklist must be a filename inside GameData/Tracks/MatchSettings')
    trackdir = str(getattr(aseco.server, 'trackdir', '') or '')
    if not trackdir or not Path(trackdir).is_absolute():
        raise ManagementError('Dedicated-server track directory is not a local absolute path; cleanup refused')
    folder = Path(trackdir).resolve() / 'MatchSettings'
    path = folder / filename
    if folder.is_symlink() or path.is_symlink() or path.resolve().parent != folder:
        raise ManagementError('MatchSettings must be a regular local file inside the dedicated track directory')
    if path.stat().st_size > 4 * 1024 * 1024:
        raise ManagementError('MatchSettings exceeds the safe editing size limit')
    content = path.read_bytes()
    _playlist_document(content.decode('utf-8-sig'))
    return path, hashlib.sha256(content).hexdigest()


async def _database_target(conn):
    async with conn.cursor() as cur:
        await cur.execute('SELECT DATABASE()')
        row = await cur.fetchone()
        database = str(row[0] or '') if row else ''
        if not database or database.lower() in SYSTEM_DATABASES:
            raise ManagementError('Refusing cleanup of an unset or system database')
        await cur.execute('SHOW FULL TABLES')
        tables = tuple(sorted(str(row[0]) for row in await cur.fetchall() if row[1] == 'BASE TABLE'))
        await cur.execute('SHOW TRIGGERS')
        if await cur.fetchall():
            raise ManagementError('Database contains custom triggers; use an external database backup/reset tool instead')
        return database, tables


async def prepare(aseco, mode):
    path, revision = None, ''
    if mode in ('ms', 'all'):
        path, revision = await file_io(_playlist_target, aseco)
    database, tables, settings = '', (), {}
    if mode in ('db', 'all'):
        service = get_localdb_service(aseco)
        getter = getattr(service, 'connection_settings', None)
        pool = await localdb_get_pool(aseco)
        if pool is None or not callable(getter):
            raise ManagementError('Local database maintenance interface is unavailable')
        settings = getter()
        async with pool.acquire() as conn:
            database, tables = await _database_target(conn)
        if str(settings.get('db') or '') != database:
            raise ManagementError('Configured database differs from the connected database; cleanup refused')
    return Plan(mode, database, tables, settings, path, revision)


def _backup_directory(root):
    parent = Path(root).resolve() / '.server-cleanup'
    if parent.is_symlink():
        raise ManagementError('Cleanup backup directory may not be a symbolic link')
    parent.mkdir(mode=0o700, exist_ok=True)
    folder = parent / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + secrets.token_hex(4))
    folder.mkdir(mode=0o700)
    return folder


def _write(path, text, *, append=False):
    with path.open('ab' if append else 'xb') as stream:
        if not append:
            os.chmod(path, 0o600)
        stream.write(text.encode('utf-8'))
        stream.flush()
        os.fsync(stream.fileno())


async def _database_backup(conn, plan, path):
    async with conn.cursor() as cur:
        await cur.execute('SET SESSION sql_mode="NO_AUTO_VALUE_ON_ZERO"')
    await file_io(_write, path, 'SET NAMES utf8mb4;\nSET FOREIGN_KEY_CHECKS=0;\n'
                  'SET SQL_MODE="NO_AUTO_VALUE_ON_ZERO";\nUSE ' + _identifier(plan.database) + ';\n')
    for table in plan.tables:
        quoted = _identifier(table)
        async with conn.cursor() as cur:
            await cur.execute('SHOW CREATE TABLE ' + quoted)
            ddl = (await cur.fetchone())[1]
            await file_io(_write, path, f'\nDROP TABLE IF EXISTS {quoted};\n{ddl};\n', append=True)
            await cur.execute('SHOW COLUMNS FROM ' + quoted)
            columns = [row[0] for row in await cur.fetchall() if 'GENERATED' not in str(row[5]).upper()]
        if not columns:
            raise ManagementError('Cannot safely back up table with no writable columns: ' + table)
        names = ','.join(_identifier(column) for column in columns)
        async with conn.cursor(aiomysql.SSCursor) as cur:
            await cur.execute(f'SELECT {names} FROM {quoted}')
            while rows := await cur.fetchmany(256):
                values = []
                for row in rows:
                    values.append('(' + ','.join("X'" + value.hex() + "'" if isinstance(value, bytes)
                                  else conn.escape(value) for value in row) + ')')
                await file_io(_write, path, f'INSERT INTO {quoted} ({names}) VALUES ' +
                              ',\n'.join(values) + ';\n', append=True)
    await file_io(_write, path, '\nSET FOREIGN_KEY_CHECKS=1;\n', append=True)


async def _truncate(conn, plan, completed):
    async with conn.cursor() as cur:
        await cur.execute('SELECT @@FOREIGN_KEY_CHECKS')
        previous = int((await cur.fetchone())[0])
        await cur.execute('SET FOREIGN_KEY_CHECKS=0')
        try:
            for table in plan.tables:
                await cur.execute('TRUNCATE TABLE ' + _identifier(plan.database) + '.' + _identifier(table))
                completed.append(table)
        finally:
            await cur.execute('SET FOREIGN_KEY_CHECKS=' + str(previous))


async def execute(aseco, plan):
    """MS runs live; DB/all run after controller writers close, then request re-exec."""
    folder = await file_io(_backup_directory, aseco._base_dir)
    logger.warning('[CleanupServer] Starting %s; backups: %s', plan.mode, folder)
    report = {'mode': plan.mode, 'database': plan.database, 'tables_cleared': [],
              'matchsettings_cleared': False, 'retained_map_uid': None, 'success': False}
    conn = None
    try:
        if plan.database:
            conn = await aiomysql.connect(**plan.settings, charset='utf8mb4', autocommit=True)
            if await _database_target(conn) != (plan.database, plan.tables):
                raise ManagementError('Database/table list changed since review; no cleanup performed')
            await _database_backup(conn, plan, folder / 'database.sql')
        if plan.matchsettings:
            path, revision = await file_io(_playlist_target, aseco)
            if (path, revision) != (plan.matchsettings, plan.revision):
                raise ManagementError('MatchSettings changed since review; no cleanup performed')
            content = await file_io(path.read_text, encoding='utf-8-sig')
            await file_io(_write, folder / 'MatchSettings.txt', content)
            # Read authoritative dedicated state, not a possibly stale controller map cache.
            current = await aseco.client.query('GetCurrentChallengeInfo')
            uid = str(current.get('UId') or current.get('Uid') or '') if isinstance(current, dict) else ''
            filename = str(current.get('FileName') or '') if isinstance(current, dict) else ''
            if not uid or not filename:
                raise ManagementError('Cannot identify the running map; no cleanup performed')
            await file_io(update_file, path, lambda text: _keep_current_playlist(text, uid, filename), expected=plan.revision,
                          validator=ET.fromstring)
            report['matchsettings_cleared'] = True
            report['retained_map_uid'] = uid
        if conn is not None:
            await _truncate(conn, plan, report['tables_cleared'])
        report['success'] = True
        logger.warning('[CleanupServer] Complete: %s. Dedicated stays online; controller %s. Backups: %s',
                       plan.mode, 'will restart' if plan.database else 'stays online', folder)
    except BaseException as error:
        report['error'] = str(error)
        logger.error('[CleanupServer] FAILED; partial results: %s; backups: %s', report, folder)
        raise
    finally:
        if conn is not None:
            conn.close()
        await file_io(_write, folder / 'result.json', json.dumps(report, indent=2) + '\n')
    return bool(plan.database)


async def command(aseco, admin, args):
    from .command_router import _reply
    async def reply(text):
        await _reply(aseco, admin.login, '{#server}> ' + text)
    if not aseco.is_master_admin(admin):
        await reply('{#error}Cleanup is restricted to MasterAdmins.')
        return
    if not args or args == ['help']:
        await reply('{#message}//cleanupserver db: erase ALL rows in this controller database, including optional apps and player preferences.')
        await reply('{#message}//cleanupserver ms: keep only the running map in MatchSettings; preserve game settings and map files.')
        await reply('{#message}//cleanupserver all: both. Each action previews targets and requires confirmation; backups are mandatory.')
        await reply('{#message}Dedicated server stays online. ms runs live; db/all restart only PyXaseco to clear cached IDs. Never use a shared database.')
        return
    if args[0] not in ('db', 'ms', 'all') or (len(args) != 1 and (len(args) != 3 or args[1] != 'confirm')):
        await reply('{#error}Usage: //cleanupserver <db|ms|all>, then the displayed confirmation command.')
        return
    try:
        if getattr(aseco, '_shutdown_requested', False):
            raise ManagementError('Controller is already shutting down')
        pending = getattr(aseco, '_cleanup_pending', {})
        if len(args) == 1:
            plan = await prepare(aseco, args[0])
            token = secrets.token_hex(4)
            aseco._cleanup_pending = {admin.login: (admin, plan, token, monotonic() + TTL)}
            if plan.database:
                await reply(f'{{#error}}Erase ALL data in database [{plan.database}], {len(plan.tables)} table(s); preserve schema. Shared databases affect every user of that database!')
            if plan.matchsettings:
                await reply(f'{{#message}}Keep only the running map in MatchSettings: {plan.matchsettings}. Game settings and map files are preserved.')
            await reply('{#message}Dedicated stays online; ms runs live. db/all briefly restart PyXaseco; records during that gap are not tracked. A failed DB cleanup leaves PyXaseco stopped for review.')
            await reply(f'{{#message}}Backups: .server-cleanup/. Confirm within {TTL}s: //cleanupserver {plan.mode} confirm {token}')
            return
        saved = pending.pop(admin.login, None)
        if (not saved or saved[0] is not admin or saved[1].mode != args[0]
                or not secrets.compare_digest(saved[2], args[2]) or monotonic() > saved[3]):
            raise ManagementError('Confirmation is missing, expired or incorrect; request a new preview')
        plan = saved[1]
        if await prepare(aseco, plan.mode) != plan:
            raise ManagementError('Cleanup targets changed; request a new preview')
        if plan.database:
            await reply('{#message}Cleanup confirmed. Dedicated stays online; PyXaseco will restart after successful DB cleanup. Backups: .server-cleanup/.')
            await aseco.shutdown(after_close=lambda: execute(aseco, plan))
        else:
            await execute(aseco, plan)
            await reply('{#message}MatchSettings cleaned: only the running map remains. Server and PyXaseco stay online. Backups: .server-cleanup/.')
    except (OSError, ValueError, aiomysql.Error, ET.ParseError) as error:
        logger.warning('[CleanupServer] Refused: %s', error)
        await reply('{#error}Cleanup refused: ' + str(error))
