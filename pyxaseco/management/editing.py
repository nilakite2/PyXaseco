"""Small text/config helpers shared by headless and desktop administration."""

import re

from .config_store import ManagementError


def edit_dotenv(text, path, value):
    if (len(path) != 1 or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', path[0])
            or not isinstance(value, str) or any(char in value for char in '\r\n\0')
            or value != value.strip().strip('"').strip("'")):
        raise ManagementError('Use an existing .env key and a single-line value representable by the controller parser')
    if value and path[0] in {'TM_PORT', 'DB_PORT', 'TM_TIMEOUT'}:
        try:
            number = int(value)
        except ValueError as exc:
            raise ManagementError('This environment setting requires an integer') from exc
        if number <= 0 or (path[0].endswith('PORT') and number > 65535):
            raise ManagementError('Environment port must be 1-65535 and timeout must be positive')
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if line.lstrip().startswith('#'):
            continue
        key, separator, _old = line.partition('=')
        if separator and key.strip() == path[0]:
            newline = '\r\n' if line.endswith('\r\n') else '\n' if line.endswith('\n') else ''
            lines[index] = key + '=' + value + newline
            return ''.join(lines)
    raise ManagementError('Edits require an existing .env setting')


def secret_key(path):
    return any(word in str(key).lower() for key in path
               for word in ('password', 'token', 'secret', 'webhook', 'authorization', 'api_key'))


def origin_hints(relative):
    if relative == '.env':
        return ['Inherited environment values take precedence over .env. Editing this file requires restart.']
    if relative == 'config.toml':
        return ['TM_*, DB_*, DEDI_* and other inherited/.env variables may override TOML. '
                'This console cannot inspect a different service account\'s inherited environment.']
    return []
