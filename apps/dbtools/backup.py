"""Private, manifest-owned SQL backups; no shell commands or database writes."""

from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import time

import aiomysql

from pyxaseco.core.file_io import file_io
from pyxaseco.management.config_store import ManagementError


MARKER = 'pyxaseco-dbtools-v1'
ID = re.compile(r'[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}')
SYSTEM_DATABASES = {'mysql', 'sys', 'information_schema', 'performance_schema'}
LIVE_WARNING = 'Best-effort live export: concurrent writes may make tables reflect different moments.'
FILES = {'manifest.json', 'manifest.json.tmp', 'database.sql', 'database.sql.gz',
         'database.sql.part', 'database.sql.gz.part'}


def directory(root, relative):
    root = Path(root).resolve()
    relative = Path(relative)
    target = root / relative
    if relative.is_absolute() or target.is_symlink() or target.resolve() == root or not target.resolve().is_relative_to(root):
        raise ManagementError('Backup directory must be a subfolder inside the controller folder.')
    return target.resolve()


def identity(settings):
    return {'host': str(settings.get('host') or '127.0.0.1'), 'port': int(settings.get('port') or 3306),
            'database': str(settings.get('db') or '')}


def _folder(parent, identifier):
    if not ID.fullmatch(identifier):
        raise ManagementError('Invalid backup ID; use /dbtools listbackups.')
    path = parent / identifier
    if path.is_symlink() or path.resolve().parent != parent.resolve() or not path.is_dir():
        raise ManagementError('Backup folder is unavailable or unsafe.')
    return path


def _manifest(path, data):
    temporary = path / 'manifest.json.tmp'
    if temporary.is_symlink() or (path / 'manifest.json').is_symlink():
        raise ManagementError('Backup manifest may not be a symbolic link.')
    with temporary.open('wb') as stream:
        os.chmod(temporary, 0o600)
        stream.write((json.dumps(data, indent=2, sort_keys=True) + '\n').encode('utf-8'))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path / 'manifest.json')


def inspect(parent, identifier, source):
    path = _folder(parent, identifier)
    manifest = path / 'manifest.json'
    if manifest.is_symlink() or manifest.stat().st_size > 262144:
        raise ManagementError('Invalid backup manifest.')
    raw = manifest.read_bytes()
    data = json.loads(raw)
    if (data.get('owner') != MARKER or data.get('id') != identifier or data.get('source') != source
            or data.get('status') not in ('complete', 'incomplete', 'failed')
            or data.get('file') not in ('database.sql', 'database.sql.gz')):
        raise ManagementError('Backup is not owned by this app/database.')
    created = datetime.fromisoformat(data['created_at'])
    if created.tzinfo is None:
        raise ManagementError('Backup timestamp must include UTC timezone.')
    stamps = []
    for name in (data['file'], data['file'] + '.part'):
        artifact = path / name
        if artifact.is_symlink():
            raise ManagementError('Backup SQL may not be a symbolic link.')
        if artifact.exists():
            stat = artifact.stat()
            stamps.append((name, stat.st_size, stat.st_mtime_ns))
    if data['status'] == 'complete' and not any(stamp[0] == data['file'] for stamp in stamps):
        raise ManagementError('Completed backup SQL file is missing.')
    return {**data, 'bytes': sum(stamp[1] for stamp in stamps), 'timestamp': created.timestamp(),
            'revision': hashlib.sha256(raw + repr(stamps).encode('utf-8')).hexdigest()}


def scan(parent, source):
    if not parent.exists():
        return []
    if parent.is_symlink():
        raise ManagementError('Unsafe backup directory.')
    rows = []
    for path in parent.iterdir():
        if not ID.fullmatch(path.name):
            continue
        try:
            rows.append(inspect(parent, path.name, source))
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if len(rows) > 5000:
            raise ManagementError('More than 5000 backups; archive older backup folders externally.')
    return sorted(rows, key=lambda row: row['created_at'], reverse=True)


def remove(parent, identifier, source, expected):
    row = inspect(parent, identifier, source)
    if row['revision'] != expected:
        raise ManagementError('Backup changed since review; request a new deletion confirmation.')
    path = _folder(parent, identifier)
    entries = list(path.iterdir())
    if any(entry.name not in FILES or entry.is_symlink() or not entry.is_file() for entry in entries):
        raise ManagementError('Backup folder contains unexpected files; deletion refused.')
    # Only known files from one reviewed app-owned folder are deleted.
    for entry in sorted(entries, key=lambda entry: entry.name == 'manifest.json'):
        entry.unlink()
    path.rmdir()


def prune(parent, source, days, keep_last, protected, *, now=None):
    if days == 0:
        return 0
    cutoff = (time.time() if now is None else now) - days * 86400
    complete = [row for row in scan(parent, source) if row['status'] == 'complete']
    deleted = 0
    for row in complete[max(1, keep_last):]:
        if row['id'] != protected and row['timestamp'] < cutoff:
            remove(parent, row['id'], source, row['revision'])
            deleted += 1
    return deleted


def _start(parent, source, compressed, engines=None):
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    identifier = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + secrets.token_hex(4)
    path = parent / identifier
    path.mkdir(mode=0o700)
    data = {'owner': MARKER, 'id': identifier, 'source': source, 'status': 'incomplete',
            'created_at': datetime.now(timezone.utc).isoformat(),
            'file': 'database.sql.gz' if compressed else 'database.sql',
            'scope': 'base table definitions and data', 'consistency': 'InnoDB snapshot'}
    data['table_engines'] = dict(engines or {})
    legacy = [name for name, engine in data['table_engines'].items() if str(engine).lower() != 'innodb']
    if legacy:
        data.update(consistency='Best-effort live export', non_transactional_tables=legacy, warning=LIVE_WARNING)
    _manifest(path, data)
    return path, data


class Writer:
    def __init__(self, path, compressed, maximum):
        self.raw = path.open('xb')
        try:
            os.chmod(path, 0o600)
            self.stream = gzip.GzipFile(fileobj=self.raw, mode='wb', mtime=0) if compressed else self.raw
        except BaseException:
            self.raw.close()
            raise
        self.maximum, self.written = maximum, 0

    def write(self, text):
        content = text.encode('utf-8')
        if self.written + len(content) > self.maximum:
            raise ManagementError('Backup exceeded max_size_mb; incomplete output is not a successful backup.')
        self.stream.write(content)
        self.written += len(content)

    def close(self):
        try:
            if self.stream is not self.raw:
                self.stream.close()
            self.raw.flush()
            os.fsync(self.raw.fileno())
        finally:
            self.raw.close()


def _publish(path, data):
    target = path / data['file']
    os.replace(path / (data['file'] + '.part'), target)
    digest = hashlib.sha256()
    with target.open('rb') as stream:
        while block := stream.read(262144):
            digest.update(block)
    data.update(status='complete', sha256=digest.hexdigest(), bytes=target.stat().st_size)
    _manifest(path, data)
    return inspect(path.parent, path.name, data['source'])


def quoted(value):
    return '`' + value.replace('`', '``') + '`'


async def catalog(conn, database):
    async with conn.cursor() as cur:
        await cur.execute('SELECT DATABASE()')
        row = await cur.fetchone()
        if not row or row[0] != database or database.lower() in SYSTEM_DATABASES:
            raise ManagementError('Backup target is unset, a system database, or differs from the configured database.')
        await cur.execute('''SELECT TABLE_NAME, ENGINE FROM information_schema.TABLES
            WHERE TABLE_SCHEMA=DATABASE() ORDER BY TABLE_NAME''')
        tables = tuple(await cur.fetchall())
        unsupported = [name for name, engine in tables if str(engine).lower() not in ('innodb', 'myisam', 'aria')]
        if unsupported:
            raise ManagementError('Backup supports InnoDB/MyISAM/Aria base tables; unsupported tables/views: ' + ', '.join(unsupported))
        await cur.execute('SHOW TRIGGERS')
        if await cur.fetchall():
            raise ManagementError('Custom triggers require an external database backup tool; no partial backup was accepted.')
    return tables


async def create(settings, parent, compressed=True, max_size_mb=1024):
    source = identity(settings)
    if not source['database'] or source['database'].lower() in SYSTEM_DATABASES:
        raise ManagementError('Refusing backup of an unset or system database.')
    conn = writer = path = data = None
    try:
        options = {**settings, 'charset': 'utf8mb4', 'autocommit': True, 'connect_timeout': 10}
        conn = await aiomysql.connect(**options)
        tables = await catalog(conn, source['database'])
        path, data = await file_io(_start, parent, source, compressed, dict(tables))
        writer = await file_io(Writer, path / (data['file'] + '.part'), compressed, max_size_mb * 1024 * 1024)
        async with conn.cursor() as cur:
            await cur.execute("SET SESSION sql_mode='NO_AUTO_VALUE_ON_ZERO'")
            # A snapshot protects only the InnoDB portion of a mixed database.
            if any(str(engine).lower() == 'innodb' for _name, engine in tables):
                await cur.execute('SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ')
                await cur.execute('START TRANSACTION WITH CONSISTENT SNAPSHOT')
        await file_io(writer.write, '-- PyXaseco table backup. Select the target database before importing.\n'
                      '-- Import replaces target tables. Keep controllers stopped during restoration.\n'
                      '-- Consistency: ' + data['consistency'] + '.\n' +
                      ('-- ' + data['warning'] + '\n' if data.get('warning') else '') +
                      'SET NAMES utf8mb4;\nSET FOREIGN_KEY_CHECKS=0;\nSET SQL_MODE="NO_AUTO_VALUE_ON_ZERO";\n')
        definitions, row_count = {}, 0
        for table, _engine in tables:
            name = quoted(table)
            async with conn.cursor() as cur:
                await cur.execute('SHOW CREATE TABLE ' + name)
                ddl = (await cur.fetchone())[1]
                definitions[table] = re.sub(r'AUTO_INCREMENT=\d+', 'AUTO_INCREMENT=?', ddl)
                await cur.execute('SHOW COLUMNS FROM ' + name)
                columns = [row[0] for row in await cur.fetchall()
                           if not any(kind in str(row[5]).upper() for kind in ('VIRTUAL GENERATED', 'STORED GENERATED', 'PERSISTENT'))]
            if not columns:
                raise ManagementError('No writable columns found in table: ' + table)
            names = ','.join(quoted(column) for column in columns)
            await file_io(writer.write, f'\nDROP TABLE IF EXISTS {name};\n{ddl};\n')
            async with conn.cursor(aiomysql.SSCursor) as cur:
                await cur.execute(f'SELECT {names} FROM {name}')
                while rows := await cur.fetchmany(256):
                    values, size = [], 0
                    for row in rows:
                        text = '(' + ','.join("X'" + bytes(value).hex() + "'" if isinstance(value, (bytes, bytearray, memoryview))
                                              else conn.escape(value) for value in row) + ')'
                        if values and size + len(text.encode('utf-8')) > 1024 * 1024:
                            await file_io(writer.write, f'INSERT INTO {name} ({names}) VALUES ' + ',\n'.join(values) + ';\n')
                            values, size = [], 0
                        values.append(text)
                        size += len(text.encode('utf-8'))
                        row_count += 1
                    if values:
                        await file_io(writer.write, f'INSERT INTO {name} ({names}) VALUES ' + ',\n'.join(values) + ';\n')
        if await catalog(conn, source['database']) != tables:
            raise ManagementError('Table list/engines changed during backup; output was not accepted.')
        async with conn.cursor() as cur:
            for table, original in definitions.items():
                await cur.execute('SHOW CREATE TABLE ' + quoted(table))
                ddl = (await cur.fetchone())[1]
                if re.sub(r'AUTO_INCREMENT=\d+', 'AUTO_INCREMENT=?', ddl) != original:
                    raise ManagementError('Table definition changed during backup: ' + table)
        await file_io(writer.write, '\nSET FOREIGN_KEY_CHECKS=1;\n')
        await file_io(writer.close)
        writer = None
        data.update(tables=len(tables), rows=row_count)
        return await file_io(_publish, path, data)
    except BaseException as error:
        if writer is not None:
            try:
                await file_io(writer.close)
            except Exception:
                pass
        if path is not None:
            data.update(status='failed', error_type=type(error).__name__)
            await file_io(_manifest, path, data)
        raise
    finally:
        if conn is not None:
            conn.close()
