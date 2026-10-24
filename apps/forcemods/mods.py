"""TMF environment/mod validation and native forced-mod settings."""

from dataclasses import dataclass
from urllib.parse import urlsplit

from pyxaseco.app_config import as_bool


ENVIRONMENTS = ('Stadium', 'Island', 'Speed', 'Rally', 'Bay', 'Coast', 'Alpine')
MODES = ('off', 'sequential', 'random')
MAX_MODS = 1000


def environment(value):
    name = str(value).strip().lower()
    names = {env.lower(): env for env in ENVIRONMENTS}
    names.update({'desert': 'Speed', 'snow': 'Alpine'})
    names.update({str(i + 1): env for i, env in enumerate(ENVIRONMENTS)})
    if name not in names:
        raise ValueError('Unknown TMF environment: ' + str(value))
    return names[name]


def mode(value):
    name = str(value).strip().lower()
    name = {'0': 'off', '1': 'sequential', '2': 'random', 'disabled': 'off', 'seq': 'sequential'}.get(name, name)
    if name not in MODES:
        raise ValueError('ForceMods mode must be off, sequential or random.')
    return name


def mod_url(value):
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise ValueError('Supply a direct HTTP mod ZIP URL.')
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme.lower() in ('http', 'https') and parsed.hostname
                 and not parsed.username and not parsed.password and not parsed.fragment)
        parsed.port
    except ValueError:
        valid = False
    if not valid or any(ch.isspace() or ord(ch) < 32 or ch in '$[]<>"' for ch in value):
        raise ValueError('Supply a direct HTTP mod ZIP URL without credentials, spaces or formatting.')
    return 'http://' + value.split('://', 1)[1]


@dataclass(frozen=True)
class Mod:
    key: str
    name: str
    url: str
    environments: tuple[str, ...]
    enabled: bool


def parse_mods(section):
    rows = section.get('mods', {})
    if not isinstance(rows, dict) or len(rows) > MAX_MODS:
        raise ValueError(f'forcemods.mods must be a table with at most {MAX_MODS} entries.')
    result = {}
    for key, row in rows.items():
        if not isinstance(row, dict):
            raise ValueError('Each ForceMods entry must be its own TOML table: ' + key)
        name = row.get('name', key)
        if not isinstance(name, str) or not name.strip() or len(name) > 128 or any(ord(c) < 32 for c in name):
            raise ValueError('Invalid ForceMods name: ' + key)
        envs = row.get('environments', '')
        if isinstance(envs, str):
            envs = envs.split(',') if envs.strip() else list(ENVIRONMENTS)
        if not isinstance(envs, list) or not envs:
            raise ValueError('Mod environments must be a comma-separated string or non-empty list: ' + key)
        targets = tuple(dict.fromkeys(environment(env) for env in envs))
        enabled = as_bool(row.get('enabled', True))
        url = row.get('url', '')
        if not isinstance(url, str):
            raise ValueError('Mod URL must be a string: ' + key)
        url = mod_url(url) if url or enabled else ''
        result[key] = Mod(key, name.strip(), url, targets, enabled)
    return result


def native_settings(raw):
    if not isinstance(raw, dict) or type(raw.get('Override')) is not bool or not isinstance(raw.get('Mods'), list):
        raise ValueError('GetForcedMods returned invalid settings; no mods were changed.')
    mods = []
    for item in raw['Mods']:
        if not isinstance(item, dict):
            raise ValueError('GetForcedMods returned an invalid mod entry.')
        env, url = item.get('Env', item.get('EnvName')), item.get('Url')
        if not isinstance(env, str) or not isinstance(url, str):
            raise ValueError('GetForcedMods returned an invalid mod entry.')
        mods.append({'Env': env, 'Url': url})
    return raw['Override'], mods


def signature(settings):
    override, mods = settings
    return override, tuple(sorted((item['Env'], item['Url']) for item in mods))
