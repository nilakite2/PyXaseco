"""Private-stdin worker executed by the selected controller Python, never by Qt."""

import importlib
import importlib.metadata
import json
from pathlib import Path
import re
import sys


def requirements(path=None, *, text=None):
    result = {}
    for line in (text if text is not None else Path(path).read_text(encoding='utf-8')).splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        match = re.fullmatch(r'([A-Za-z0-9_-]+)==([A-Za-z0-9_.+-]+)', line)
        if not match:
            raise ValueError('Only exact pinned package requirements are supported')
        result[match[1]] = match[2]
    if not result:
        raise ValueError('No pinned requirements found')
    return result


def dependencies(path=None, *, text=None):
    packages = []
    for name, expected in requirements(path, text=text).items():
        try:
            installed = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            installed = None
        module = {'PyMySQL': 'pymysql'}.get(name, name.replace('-', '_'))
        try:
            importlib.import_module(module)
            imported = True
        except (ImportError, OSError):
            imported = False
        packages.append({'name': name, 'required': expected, 'installed': installed,
                         'importable': imported, 'ok': installed == expected and imported})
    return {'python': sys.version.split()[0], 'supported': sys.version_info >= (3, 12),
            'isolated': sys.prefix != sys.base_prefix, 'packages': packages,
            'ready': all(row['ok'] for row in packages)}


def database(settings, *, create=False, schema=None):
    import pymysql
    name, user = settings['DB_NAME'], settings['DB_USER']
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}', name):
        raise ValueError('Use a database name containing letters, numbers and underscores')
    options = dict(host=settings.get('DB_HOST') or '127.0.0.1', port=int(settings.get('DB_PORT') or 3306),
                   connect_timeout=8, read_timeout=15, write_timeout=15, charset='utf8mb4', autocommit=True)
    if create:
        user_host = settings.get('DB_USER_HOST', 'localhost')
        if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,253}', user_host):
            raise ValueError('Use an explicit database-user host, without wildcards')
        if (not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,31}', user)
                or user.lower() in {'root', 'mysql', 'mariadb', 'admin'}):
            raise ValueError('Create mode requires a new dedicated database user')
        statements = [item.strip() for item in Path(schema).read_text().split(';') if item.strip()]
        if not statements or any(not re.match(r'CREATE TABLE IF NOT EXISTS `\w+`\s*\(', item) for item in statements):
            raise ValueError('The supplied schema is not a fresh-table-only schema')
        admin = pymysql.connect(**options, user=settings['admin_user'], password=settings.get('admin_password', ''))
        try:
            with admin.cursor() as cursor:
                cursor.execute('SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s', (name,))
                if cursor.fetchone():
                    raise ValueError('Database already exists; use existing mode. No existing database was changed')
                cursor.execute('SELECT User FROM mysql.user WHERE User=%s', (user,))
                if cursor.fetchone():
                    raise ValueError('Database user already exists; choose a new instance-specific user')
                cursor.execute(f'CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci')
                cursor.execute('CREATE USER %s@%s IDENTIFIED BY %s', (user, user_host, settings.get('DB_PASSWORD', '')))
                cursor.execute(f'GRANT ALL PRIVILEGES ON `{name}`.* TO %s@%s', (user, user_host))
        finally:
            admin.close()
    connection = pymysql.connect(**options, user=user, password=settings.get('DB_PASSWORD', ''), database=name)
    try:
        with connection.cursor() as cursor:
            if create:
                for statement in statements:
                    cursor.execute(statement)
            cursor.execute('SELECT 1')
            cursor.fetchone()
    finally:
        connection.close()
    return {'ready': True, 'created': create, 'schema_initialized': create, 'database': name, 'user': user}


def main():
    try:
        raw = sys.stdin.read(65537)
        if len(raw) > 65536:
            raise ValueError('Prerequisite request exceeds 64 KiB')
        request = json.loads(raw)
        if request['action'] == 'dependencies':
            result = dependencies(request.get('requirements'), text=request.get('requirements_text'))
        elif request['action'] == 'database':
            result = database(request['settings'], create=request.get('create', False), schema=request.get('schema'))
        else:
            raise ValueError('Unknown prerequisite action')
        print(json.dumps(result))
        return 0
    except ValueError as exc:
        print(json.dumps({'error': str(exc)}))
        return 2
    except Exception as exc:
        # SQL/driver errors can contain passwords or complete statements. Never relay them.
        print(json.dumps({'error': 'Prerequisite check failed (' + type(exc).__name__ +
            '); check connection, credentials and permissions. Partial new DB/user creation, if any, is retained.'}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
